"""ReversalService — tree / preview / reverse по журналу действий.

Preview-first с тремя зонами (отменится 🔴 / останется ⚪ / блокировки 🚫);
``plan_token`` — подписанный снимок мира на момент preview, инвалидируется
(StalePlanToken) при любом изменении ledger/журнала к моменту reverse.
Каскад исполняется строго в обратном топологическом порядке по
``depends_on``; уже отменённые узлы пропускаются.
"""
from __future__ import annotations

import base64
import hashlib
import heapq
import hmac
import json
from dataclasses import dataclass, field
from decimal import Decimal

from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.models.action_journal import Action, ActionStatus
from app.reversal.errors import (
    AlreadyReversed,
    CoverageShortfall,
    HasDependentActions,
    NotAllowed,
    StalePlanToken,
)
from app.reversal.action_compensator import StockActionCompensator
from app.reversal.base import Compensator, ReversalPlan, ReversalResult
from app.reversal.stock_compensator import StockCompensator
from app.stock.models import StockTransaction


# ─── Структуры preview/tree ──────────────────────────────────────────────────


@dataclass
class ActionNode:
    """Узел дерева/preview: действие со статусом и зависимостями."""

    id: int
    action_type: str
    ref_id: int | None
    status: str
    depends_on: list[int] = field(default_factory=list)

    @classmethod
    def of(cls, action: Action) -> "ActionNode":
        return cls(
            id=action.id,
            action_type=action.action_type,
            ref_id=action.ref_id,
            status=action.status.value if isinstance(action.status, ActionStatus) else str(action.status),
            depends_on=list(action.depends_on or []),
        )


@dataclass
class TreeNode(ActionNode):
    children: list["TreeNode"] = field(default_factory=list)


@dataclass
class ActionTree:
    root: TreeNode
    total_nodes: int


@dataclass
class Blocker:
    kind: str  # has_dependents | coverage | not_allowed | already_reversed | not_found
    node_id: int | None
    detail: str
    deficit: Decimal | None = None
    chain: list[int] | None = None  # для has_dependents


@dataclass
class ReversalPreview:
    action_id: int
    cascade: bool
    revert: list[ActionNode]   # 🔴 отменится
    stays: list[ActionNode]    # ⚪ останется (уже отменённые — пропускаются)
    blockers: list[Blocker]    # 🚫 блокировки
    plan_token: str | None  # None при блокировках: confirm невозможен без повторного preview


@dataclass
class AmendResult:
    """Результат amend: компенсация старого + новое действие (#115)."""

    action_id: int                    # исходное (изменённое) действие
    new_action_id: int                # новое действие (amends_action_id → action_id)
    new_ref_id: int | None            # новый доменный объект (Transfer)
    compensated_tx_ids: list[int] = field(default_factory=list)
    amended_action_ids: list[int] = field(default_factory=list)   # статус → 'amended'
    reversed_action_ids: list[int] = field(default_factory=list)  # каскадные dependents → 'reversed'


@dataclass
class PurgePair:
    """Пара «исходная проводка + её компенсация» (hard-чистка, #118)."""

    source_tx_id: int
    reverse_tx_id: int
    product_id: int
    quantity: Decimal


@dataclass
class PurgePlan:
    """Отчёт hard-purge: пары к удалению; plan_token — только в dry_run."""

    action_id: int
    pairs: list[PurgePair] = field(default_factory=list)
    plan_token: str | None = None
    deleted_tx_ids: list[int] = field(default_factory=list)  # заполнено после confirm


def _sign_payload(payload: dict) -> str:
    raw = base64.urlsafe_b64encode(
        json.dumps(payload, sort_keys=True, ensure_ascii=False).encode()
    ).decode().rstrip("=")
    sig = hmac.new(settings.SECRET_KEY.encode(), raw.encode(), hashlib.sha256).hexdigest()
    return f"{raw}.{sig}"


def _verify_raw_token(token: str) -> dict:
    try:
        raw, sig = token.rsplit(".", 1)
        expected = hmac.new(settings.SECRET_KEY.encode(), raw.encode(), hashlib.sha256).hexdigest()
        if not hmac.compare_digest(sig, expected):
            raise ValueError("bad signature")
        padded = raw + "=" * (-len(raw) % 4)
        payload = json.loads(base64.urlsafe_b64decode(padded.encode()).decode())
        if not isinstance(payload, dict):
            raise ValueError("not a dict")
        return payload

    except Exception as exc:  # noqa: BLE001 — любая порча токена = stale
        raise StalePlanToken("plan_token недействителен") from exc


def _verify_token(token: str, *, kind: str = "reverse") -> dict:
    """Распаковать и проверить plan_token; ``kind`` различает операции
    (reverse/amend): токен preview_amend не годится для reverse и наоборот."""
    payload = _verify_raw_token(token)
    if payload.get("kind", "reverse") != kind:
        raise StalePlanToken(
            f"plan_token выдан для другой операции ({payload.get('kind')} ≠ {kind})"
        )
    return payload


# ─── Сервис ──────────────────────────────────────────────────────────────────


class ReversalService:
    """Единая точка отката доменных действий (ADR-0019)."""

    def __init__(self) -> None:
        self._compensators: dict[str, Compensator] = {}
        for at in ("transfer_send", "transfer_cancel"):
            self.register(at, StockCompensator(at))
        # Универсальный компенсатор доменных действий (#116 волна B):
        # shopfloor/план/импорт; seed_demo без компенсатора (решение 7).
        for at in sorted(StockActionCompensator.ACTION_TYPES):
            self.register(at, StockActionCompensator(at))

    def register(self, action_type: str, compensator: Compensator) -> None:
        self._compensators[action_type] = compensator

    def _compensator(self, action_type: str) -> Compensator | None:
        return self._compensators.get(action_type)

    # ── дерево ───────────────────────────────────────────────────────────

    async def _dependents_map(self, db: AsyncSession) -> dict[int, list[Action]]:
        """Кто зависит от кого: id действия → действия, чей depends_on его содержит."""
        actions = (
            await db.execute(select(Action).order_by(Action.id.asc()))
        ).scalars().all()
        result: dict[int, list[Action]] = {}
        for a in actions:
            for dep in a.depends_on or []:
                result.setdefault(int(dep), []).append(a)
        return result

    async def tree(self, db: AsyncSession, action_id: int) -> ActionTree:
        """Поддерево dependents (кто построен поверх данного) со статусами."""
        action = await db.get(Action, action_id)
        if action is None:
            raise ValueError(f"Action #{action_id} не найден")
        dependents = await self._dependents_map(db)

        root = TreeNode.of(action)
        count = 1
        queue = [(root, action.id)]
        seen: set[int] = {action.id}
        while queue:
            node, aid = queue.pop(0)
            for child_action in dependents.get(aid, []):
                if child_action.id in seen:
                    continue
                seen.add(child_action.id)
                child = TreeNode.of(child_action)
                node.children.append(child)
                count += 1
                queue.append((child, child_action.id))
        return ActionTree(root=root, total_nodes=count)

    # ── preview ──────────────────────────────────────────────────────────

    async def _cascade_set(
        self, db: AsyncSession, target: Action, *, cascade: bool
    ) -> tuple[list[Action], list[Action], list[Action]]:
        """(активный каскад, отменённые dependents, активные потомки
        отменённого). Цепочка собирается полностью — без break; при
        cascade=True обходится и поддерево уже отменённого dependent,
        чтобы ни один узел не потерялся из трёх зон."""
        dependents = await self._dependents_map(db)
        active: list[Action] = []
        reverted: list[Action] = []
        orphan_active: list[Action] = []  # активные потомки отменённого узла
        queue: list[tuple[int, bool]] = [(target.id, False)]  # (id, ниже_отменённого)
        seen: set[int] = {target.id}
        while queue:
            aid, below_reverted = queue.pop(0)
            for dep in dependents.get(aid, []):
                if dep.id in seen:
                    continue
                seen.add(dep.id)
                if dep.status == ActionStatus.ACTIVE:
                    if below_reverted and cascade:
                        orphan_active.append(dep)
                        queue.append((dep.id, True))
                    else:
                        active.append(dep)  # полная цепочка для блокировки/каскада
                        queue.append((dep.id, False))
                else:
                    reverted.append(dep)
                    if cascade:
                        # Поддерево отменённого не теряем: его активные
                        # потомки попадают в блокировки.
                        queue.append((dep.id, True))
        return active, reverted, orphan_active

    async def _fingerprint(self, db: AsyncSession, node_ids: list[int]) -> str:
        max_tx = await db.scalar(select(func.max(StockTransaction.id))) or 0
        max_act = await db.scalar(select(func.max(Action.id))) or 0
        statuses = sorted(f"{i}:{s}" for i, s in await self._statuses(db, node_ids))
        return f"tx:{max_tx};act:{max_act};" + ",".join(statuses)

    @staticmethod
    async def _statuses(db: AsyncSession, node_ids: list[int]) -> list[tuple[int, str]]:
        if not node_ids:
            return []
        rows = await db.execute(
            select(Action.id, Action.status).where(Action.id.in_(node_ids))
        )
        return [(int(i), s.value if isinstance(s, ActionStatus) else str(s)) for i, s in rows.all()]

    async def preview_reverse(
        self, db: AsyncSession, action_id: int, *, cascade: bool = False
    ) -> ReversalPreview:
        target = await db.get(Action, action_id)
        if target is None:
            raise ValueError(f"Action #{action_id} не найден")
        if target.status != ActionStatus.ACTIVE:
            raise AlreadyReversed(action_id)

        cascade_actions, reverted_dependents, orphan_active = await self._cascade_set(
            db, target, cascade=cascade
        )
        # 🔴 отменяется цель + активный каскад (только при cascade=True);
        # при cascade=False зависимые попадают в 🚫 блокировки.
        revert_nodes = [target] + (cascade_actions if cascade else [])
        blockers: list[Blocker] = []

        if not cascade and cascade_actions:
            blockers.append(
                Blocker(
                    kind="has_dependents",
                    node_id=target.id,
                    detail="Есть зависимые действия; включите cascade",
                    chain=[a.id for a in cascade_actions],
                )
            )

        # Активные потомки уже отменённого узла — не теряются из зон: 🚫.
        for orphan in orphan_active:
            blockers.append(
                Blocker(
                    kind="already_reversed",
                    node_id=orphan.id,
                    detail=(
                        f"Действие #{orphan.id} активно, но построено поверх "
                        f"уже отменённого — сначала пересмотрите его состояние"
                    ),
                )
            )

        for node in revert_nodes:
            comp = self._compensator(node.action_type)
            if comp is None:
                blockers.append(
                    Blocker(
                        kind="not_allowed",
                        node_id=node.id,
                        detail=f"нет компенсатора для action_type={node.action_type}",
                    )
                )
                continue
            check = await comp.check(db, node.ref_id, action_id=node.id)
            if not check.ok:
                for cb in check.blockers:
                    blockers.append(
                        Blocker(kind=cb.kind, node_id=node.id, detail=cb.detail, deficit=cb.deficit)
                    )

        # Preview-first: при блокировках план-токен не выдаётся —
        # confirm невозможен до повторного preview.
        token = (
            _sign_payload(
                {
                    "action_id": action_id,
                    "cascade": cascade,
                    "kind": "reverse",
                    "fp": await self._fingerprint(db, [n.id for n in revert_nodes]),
                }
            )
            if not blockers
            else None
        )
        return ReversalPreview(
            action_id=action_id,
            cascade=cascade,
            revert=[ActionNode.of(n) for n in revert_nodes],
            stays=[ActionNode.of(a) for a in reverted_dependents],
            blockers=blockers,
            plan_token=token,
        )

    # ── reverse ──────────────────────────────────────────────────────────

    async def reverse(
        self,
        db: AsyncSession,
        action_id: int,
        *,
        plan_token: str,
        reason: str | None = None,
        actor: str = "system",
        actor_id: int | None = None,
    ) -> ReversalResult:
        target = await db.get(Action, action_id)
        if target is None:
            raise ValueError(f"Action #{action_id} не найден")

        payload = _verify_token(plan_token)
        if int(payload.get("action_id", -1)) != action_id:
            raise StalePlanToken("plan_token выдан для другого действия")
        cascade = bool(payload.get("cascade", False))
        fresh_preview = await self.preview_reverse(db, action_id, cascade=cascade)
        current_fp = await self._fingerprint(db, [n.id for n in fresh_preview.revert])
        if payload.get("fp") != current_fp:
            raise StalePlanToken("мир изменился после preview — пересмотрите preview")
        if fresh_preview.blockers:
            self._raise_blockers(fresh_preview.blockers)

        if not fresh_preview.revert:
            # Пустой набор к откату: все узлы уже отменены, блокеров нет.
            raise AlreadyReversed(action_id)
        order = self._reverse_topological_order(
            [n.id for n in fresh_preview.revert], await self._deps_index(db)
        )
        compensated_tx_ids: list[int] = []
        reversal_action_ids: list[int] = []
        reversed_action_ids: list[int] = []

        for node_id in order:
            node = await db.get(Action, node_id)
            assert node is not None
            if node.status != ActionStatus.ACTIVE:
                continue  # уже отменён — пропуск
            comp = self._compensator(node.action_type)
            if comp is None:
                raise NotAllowed(f"нет компенсатора для action_type={node.action_type}")
            check = await comp.check(db, node.ref_id, action_id=node.id)
            if not check.ok and check.deficit:
                raise CoverageShortfall(node=node.id, deficit=check.deficit)
            plan: ReversalPlan = await comp.plan(db, node.ref_id, hard=False, action_id=node.id)
            if not plan.entries:
                raise AlreadyReversed(node.id)

            rev_action = Action(
                action_type="reversal",
                ref_id=node.ref_id,
                actor=actor,
                reason=reason,
                depends_on=list(node.depends_on or []),
            )
            db.add(rev_action)
            await db.flush()

            plan.reversal_action_id = rev_action.id
            plan.actor_id = actor_id
            plan.actor_name = actor
            plan.comment = f"reversal of action #{node.id}" + (f": {reason}" if reason else "")
            result = await comp.apply(db, plan, actor)

            node.reversed_by_action_id = rev_action.id
            node.status = ActionStatus.REVERSED
            await db.flush()

            reversal_action_ids.append(rev_action.id)
            compensated_tx_ids.extend(result.compensated_tx_ids)
            reversed_action_ids.append(node.id)

        return ReversalResult(
            action_id=action_id,
            reversal_action_id=reversal_action_ids[-1],
            compensated_tx_ids=compensated_tx_ids,
            reversed_action_ids=reversed_action_ids,
        )

    # ── amend (тикет #115) ───────────────────────────────────────────────

    @staticmethod
    def amend_changes_from_token(plan_token: str) -> dict:
        """Подписанные изменения из токена preview_amend (для REST-confirm)."""
        payload = _verify_token(plan_token, kind="amend")
        changes = payload.get("changes")
        return dict(changes) if isinstance(changes, dict) else {}


    def _amend_compensator(self, action_type: str):
        """Компенсатор с поддержкой amend (duck-typing по check_amend)."""
        comp = self._compensator(action_type)
        return comp if comp is not None and hasattr(comp, "check_amend") else None

    async def preview_amend(
        self,
        db: AsyncSession,
        action_id: int,
        changes: dict,
        *,
        cascade: bool = False,
    ) -> ReversalPreview:
        """Preview «изменить действие»: 🔴 компенсируется (+новая запись),
        ⚪ уже отменённые dependents, 🚫 блокировки; plan_token kind='amend'.

        Ограничение v1: при cascade=True зависимые действия компенсируются
        (как в reverse), их эффекты заново НЕ воспроизводятся.
        """
        target = await db.get(Action, action_id)
        if target is None:
            raise ValueError(f"Action #{action_id} не найден")
        if target.status != ActionStatus.ACTIVE:
            raise AlreadyReversed(action_id)
        comp = self._amend_compensator(target.action_type)
        if comp is None:
            raise NotAllowed(f"amend не поддерживается для action_type={target.action_type}")

        cascade_actions, reverted_dependents, orphan_active = await self._cascade_set(
            db, target, cascade=cascade
        )
        revert_nodes = [target] + (cascade_actions if cascade else [])
        blockers: list[Blocker] = []

        if not cascade and cascade_actions:
            blockers.append(
                Blocker(
                    kind="has_dependents",
                    node_id=target.id,
                    detail="Есть зависимые действия; включите cascade",
                    chain=[a.id for a in cascade_actions],
                )
            )
        for orphan in orphan_active:
            blockers.append(
                Blocker(
                    kind="already_reversed",
                    node_id=orphan.id,
                    detail=(
                        f"Действие #{orphan.id} активно, но построено поверх "
                        f"уже отменённого — сначала пересмотрите его состояние"
                    ),
                )
            )

        for node in revert_nodes:
            node_comp = (
                comp if node.id == target.id else self._compensator(node.action_type)
            )
            if node_comp is None:
                blockers.append(
                    Blocker(
                        kind="not_allowed",
                        node_id=node.id,
                        detail=f"нет компенсатора для action_type={node.action_type}",
                    )
                )
                continue
            if node.id == target.id:
                check = await node_comp.check_amend(db, node.ref_id, changes)
            else:
                check = await node_comp.check(db, node.ref_id, action_id=node.id)
            if not check.ok:
                for cb in check.blockers:
                    blockers.append(
                        Blocker(kind=cb.kind, node_id=node.id, detail=cb.detail, deficit=cb.deficit)
                    )

        token = (
            _sign_payload(
                {
                    "action_id": action_id,
                    "cascade": cascade,
                    "kind": "amend",
                    "changes": changes,
                    "fp": await self._fingerprint(db, [n.id for n in revert_nodes]),
                }
            )
            if not blockers
            else None
        )
        return ReversalPreview(
            action_id=action_id,
            cascade=cascade,
            revert=[ActionNode.of(n) for n in revert_nodes],
            stays=[ActionNode.of(a) for a in reverted_dependents],
            blockers=blockers,
            plan_token=token,
        )

    async def amend(
        self,
        db: AsyncSession,
        action_id: int,
        *,
        changes: dict,
        plan_token: str,
        reason: str | None = None,
        actor: str = "system",
        actor_id: int | None = None,
    ) -> AmendResult:
        """Атомарно: компенсировать старое действие (и каскад зависимых)
        + применить новое с ``amends_action_id``; старое получает статус
        ``'amended'`` (``reversed_by`` НЕ заполняется). Вся операция — одна
        транзакция сессии: любое исключение откатывает всё (D7-A).
        """
        from app.stock.services import StockValidationError

        target = await db.get(Action, action_id)
        if target is None:
            raise ValueError(f"Action #{action_id} не найден")

        payload = _verify_token(plan_token, kind="amend")
        if int(payload.get("action_id", -1)) != action_id:
            raise StalePlanToken("plan_token выдан для другого действия")
        if payload.get("changes") != changes:
            raise StalePlanToken("изменения не совпадают с preview — пересмотрите preview_amend")
        cascade = bool(payload.get("cascade", False))

        fresh_preview = await self.preview_amend(
            db, action_id, changes, cascade=cascade
        )
        current_fp = await self._fingerprint(db, [n.id for n in fresh_preview.revert])
        if payload.get("fp") != current_fp:
            raise StalePlanToken("мир изменился после preview — пересмотрите preview_amend")
        if fresh_preview.blockers:
            self._raise_blockers(fresh_preview.blockers)
        if not fresh_preview.revert:
            raise AlreadyReversed(action_id)

        comp = self._amend_compensator(target.action_type)
        assert comp is not None  # preview_amend уже проверил
        order = self._reverse_topological_order(
            [n.id for n in fresh_preview.revert], await self._deps_index(db)
        )

        compensated_tx_ids: list[int] = []
        amended_action_ids: list[int] = []
        reversed_action_ids: list[int] = []
        new_action_id: int | None = None
        new_ref_id: int | None = None

        for node_id in order:
            node = await db.get(Action, node_id)
            assert node is not None
            if node.status != ActionStatus.ACTIVE:
                continue  # уже отменён — пропуск
            node_comp = (
                comp if node.id == target.id else self._compensator(node.action_type)
            )
            if node_comp is None:
                raise NotAllowed(f"нет компенсатора для action_type={node.action_type}")
            check = await node_comp.check(db, node.ref_id, action_id=node.id)
            if not check.ok and check.deficit:
                raise CoverageShortfall(node=node.id, deficit=check.deficit)
            plan: ReversalPlan = await node_comp.plan(db, node.ref_id, hard=False, action_id=node.id)
            if not plan.entries:
                raise AlreadyReversed(node.id)
            # Компенсации внутри amend отличимы от reverse-компенсаций того
            # же действия (idempotency_key префикс `amend:`).
            plan.idem_prefix = "amend"

            if node.id == target.id:
                # Новое действие создаётся ПЕРЕД проводками: компенсации
                # старого и новая пара SEND/RECEIVE делят один action_id.
                new_action = Action(
                    action_type=node.action_type,
                    ref_id=None,
                    actor=actor,
                    reason=reason,
                    depends_on=list(node.depends_on or []),
                    amends_action_id=node.id,
                )
                db.add(new_action)
                await db.flush()

            plan.reversal_action_id = (
                new_action.id if node.id == target.id else plan.reversal_action_id
            )
            if node.id != target.id:
                rev_action = Action(
                    action_type="reversal",
                    ref_id=node.ref_id,
                    actor=actor,
                    reason=reason,
                    depends_on=list(node.depends_on or []),
                )
                db.add(rev_action)
                await db.flush()
                plan.reversal_action_id = rev_action.id

            plan.actor_id = actor_id
            plan.actor_name = actor
            op = "amend" if node.id == target.id else "reversal"
            plan.comment = f"{op} of action #{node.id}" + (f": {reason}" if reason else "")
            result = await node_comp.apply(db, plan, actor)

            if node.id == target.id:
                try:
                    fwd = await comp.apply_forward(
                        db,
                        action=new_action,
                        ref_id=node.ref_id,
                        changes=changes,
                        actor=actor,
                        actor_id=actor_id,
                    )
                except StockValidationError as exc:
                    # D7-A: честный дефицит — пересчёт forward-покрытия
                    # затронутого узла по фактическим остаткам (компенсации
                    # уже применены; StockValidationError поднимается до
                    # любых INSERT новой записи, транзакция чиста).
                    deficit = await comp.forward_coverage_deficit(
                        db, node.ref_id, changes
                    )
                    raise CoverageShortfall(node=node.id, deficit=deficit) from exc
                except ValueError as exc:
                    # Доменные guard'ы transfer_send (маршрут/план/лимиты):
                    # preview проверяет склад, но не маршрут — честный 403.
                    raise NotAllowed(f"amend отклонён доменом: {exc}") from exc
                new_action.ref_id = fwd["transfer_id"]
                new_action_id = new_action.id
                new_ref_id = fwd["transfer_id"]
                node.status = ActionStatus.AMENDED  # не reversed_by: это не откат
                amended_action_ids.append(node.id)
            else:
                node.reversed_by_action_id = plan.reversal_action_id
                node.status = ActionStatus.REVERSED
                reversed_action_ids.append(node.id)
            await db.flush()
            compensated_tx_ids.extend(result.compensated_tx_ids)

        assert new_action_id is not None
        return AmendResult(
            action_id=action_id,
            new_action_id=new_action_id,
            new_ref_id=new_ref_id,
            compensated_tx_ids=compensated_tx_ids,
            amended_action_ids=amended_action_ids,
            reversed_action_ids=reversed_action_ids,
        )

    # ── hard-purge (тикет #118, ADR-0019 п.7) ────────────────────────────

    async def _purge_pairs(self, db: AsyncSession, target: Action) -> list[PurgePair]:
        """Пары «исходная+компенсация» действия с проверкой условий п.3
        спеки #118; любое нарушение — NotAllowed с причиной.
        """
        if target.status != ActionStatus.REVERSED:
            raise NotAllowed(
                f"hard-purge доступен только для действий в статусе "
                f"'reversed' (текущий: '{target.status.value}')"
            )

        # Живые зависимые блокируют чистку: вся цепочка reversed/purged.
        # Транзитивный обход (реюз _cascade_set, как в preview_reverse):
        # активные узлы цепочки и «сироты» глубже уже отменённых звеньев.
        active_chain, _reverted, orphan_active = await self._cascade_set(
            db, target, cascade=True
        )
        live = active_chain + orphan_active
        if live:
            raise NotAllowed(
                "Есть живые зависимые действия: "
                + ", ".join(f"#{d.id}" for d in live)
            )

        originals = (
            await db.execute(
                select(StockTransaction)
                .where(StockTransaction.action_id == target.id)
                .order_by(StockTransaction.id.asc())
            )
        ).scalars().all()
        if not originals:
            raise NotAllowed(f"У действия #{target.id} нет проводок в ledger")

        comps = (
            await db.execute(
                select(StockTransaction)
                .where(
                    StockTransaction.reverses_id.in_([o.id for o in originals])
                )
                .order_by(StockTransaction.reverses_id.asc(), StockTransaction.id.asc())
            )
        ).scalars().all()

        by_source: dict[int, list] = {}
        for c in comps:
            by_source.setdefault(int(c.reverses_id), []).append(c)

        pairs: list[PurgePair] = []
        for orig in originals:
            matched = by_source.get(int(orig.id), [])
            if len(matched) != 1:
                raise NotAllowed(
                    f"Проводка #{orig.id} имеет {len(matched)} компенсаций — "
                    "hard-purge требует парность 1:1"
                )
            pairs.append(
                PurgePair(
                    source_tx_id=int(orig.id),
                    reverse_tx_id=int(matched[0].id),
                    product_id=int(orig.product_id),
                    quantity=orig.quantity,
                )
            )
        return pairs

    async def hard_purge(
        self,
        db: AsyncSession,
        action_id: int,
        *,
        dry_run: bool = True,
        plan_token: str | None = None,
    ) -> PurgePlan:
        """Hard-чистка полностью скомпенсированного действия (#118).

        dry_run=True: отчёт по парам без изменений + plan_token kind='purge'.
        dry_run=False: подтверждение по токену — удаление компенсаций,
        затем исходных проводок (FK reverses_id → источник) и смена статуса
        на 'purged' в одной транзакции сессии. Записи action_journal не
        удаляются (аудит).
        """
        target = await db.get(Action, action_id)
        if target is None:
            raise ValueError(f"Action #{action_id} не найден")
        pairs = await self._purge_pairs(db, target)

        if dry_run:
            return PurgePlan(
                action_id=action_id,
                pairs=pairs,
                plan_token=_sign_payload(
                    {
                        "action_id": action_id,
                        "kind": "purge",
                        "fp": await self._fingerprint(db, [action_id]),
                    }
                ),
            )

        payload = _verify_token(plan_token or "", kind="purge")
        if int(payload.get("action_id", -1)) != action_id:
            raise StalePlanToken("plan_token выдан для другого действия")
        current_fp = await self._fingerprint(db, [action_id])
        if payload.get("fp") != current_fp:
            raise StalePlanToken("мир изменился после dry_run — повторите hard-purge")

        comp_ids = [p.reverse_tx_id for p in pairs]
        source_ids = [p.source_tx_id for p in pairs]
        # Порядок п.4 спеки: сначала компенсации (их reverses_id ссылается
        # на исходные), затем исходные. Одна транзакция со сменой статуса.
        await db.execute(delete(StockTransaction).where(StockTransaction.id.in_(comp_ids)))
        await db.execute(delete(StockTransaction).where(StockTransaction.id.in_(source_ids)))
        target.status = ActionStatus.PURGED
        await db.flush()
        return PurgePlan(
            action_id=action_id,
            pairs=pairs,
            deleted_tx_ids=sorted(comp_ids + source_ids),
        )

    # ── вспомогательное ──────────────────────────────────────────────────

    @staticmethod
    def _raise_blockers(blockers: list[Blocker]) -> None:
        """Диспетч по kind блокера (не по наличию deficit)."""
        for b in blockers:
            if b.kind == "has_dependents":
                raise HasDependentActions(chain=list(b.chain or []))
            if b.kind == "coverage":
                raise CoverageShortfall(node=b.node_id or -1, deficit=b.deficit or Decimal("0"))
            if b.kind == "not_allowed":
                raise NotAllowed(b.detail)
            if b.kind == "not_found":
                raise ValueError(b.detail)
            if b.kind == "already_reversed":
                raise AlreadyReversed(b.node_id or -1)

    async def _deps_index(self, db: AsyncSession) -> dict[int, list[int]]:
        actions = (await db.execute(select(Action.id, Action.depends_on))).all()
        return {int(i): list(d or []) for i, d in actions}

    @staticmethod
    def _reverse_topological_order(
        nodes: list[int], deps: dict[int, list[int]]
    ) -> list[int]:
        """Обратный топологический порядок: dependents раньше зависимостей.

        Ребро X ≺ d для каждого d ∈ X.depends_on (X отменяется первым).
        """
        node_set = set(nodes)
        remaining = {n: 0 for n in nodes}
        unlocks: dict[int, list[int]] = {n: [] for n in nodes}
        for x in nodes:
            for d in deps.get(x, []):
                if d in node_set:
                    # X (dependent) отменяется раньше d (зависимости).
                    remaining[d] += 1
                    unlocks[x].append(d)
        heap = [-n for n, deg in remaining.items() if deg == 0]
        heapq.heapify(heap)
        order: list[int] = []
        while heap:
            n = -heapq.heappop(heap)
            order.append(n)
            for nxt in unlocks[n]:
                remaining[nxt] -= 1
                if remaining[nxt] == 0:
                    heapq.heappush(heap, -nxt)
        if len(order) != len(nodes):
            raise ValueError("цикл в depends_on — топологический порядок невозможен")
        return order


reversal_service = ReversalService()
