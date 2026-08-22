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

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.models.action_journal import Action, ActionStatus
from app.reversal.base import Compensator, ReversalPlan, ReversalResult
from app.reversal.errors import (
    AlreadyReversed,
    CoverageShortfall,
    HasDependentActions,
    NotAllowed,
    StalePlanToken,
)
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
    code: str  # HasDependentActions | CoverageShortfall | NotAllowed | AlreadyReversed
    node_id: int | None
    detail: str
    deficit: Decimal | None = None
    chain: list[int] | None = None  # для HasDependentActions


@dataclass
class ReversalPreview:
    action_id: int
    cascade: bool
    revert: list[ActionNode]   # 🔴 отменится
    stays: list[ActionNode]    # ⚪ останется (уже отменённые — пропускаются)
    blockers: list[Blocker]    # 🚫 блокировки
    plan_token: str


def _sign_payload(payload: dict) -> str:
    raw = base64.urlsafe_b64encode(
        json.dumps(payload, sort_keys=True, ensure_ascii=False).encode()
    ).decode().rstrip("=")
    sig = hmac.new(settings.SECRET_KEY.encode(), raw.encode(), hashlib.sha256).hexdigest()
    return f"{raw}.{sig}"


def _verify_token(token: str) -> dict:
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


# ─── Сервис ──────────────────────────────────────────────────────────────────


class ReversalService:
    """Единая точка отката доменных действий (ADR-0019)."""

    def __init__(self) -> None:
        self._compensators: dict[str, Compensator] = {}
        for at in ("transfer_send", "transfer_cancel"):
            self.register(at, StockCompensator(at))

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
    ) -> tuple[list[Action], list[Action]]:
        """(активный каскад, уже отменённые dependents)."""
        dependents = await self._dependents_map(db)
        active: list[Action] = []
        reverted: list[Action] = []
        queue = [target.id]
        seen: set[int] = {target.id}
        while queue:
            aid = queue.pop(0)
            for dep in dependents.get(aid, []):
                if dep.id in seen:
                    continue
                seen.add(dep.id)
                if dep.status == ActionStatus.ACTIVE and cascade:
                    active.append(dep)
                    queue.append(dep.id)
                    continue
                if not cascade:
                    active.append(dep)  # для блокировки HasDependentActions
                    break
                reverted.append(dep)
        return active, reverted

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

        cascade_actions, reverted_dependents = await self._cascade_set(
            db, target, cascade=cascade
        )
        # 🔴 отменяется цель + активный каскад (только при cascade=True);
        # при cascade=False зависимые попадают в 🚫 блокировки.
        revert_nodes = [target] + (cascade_actions if cascade else [])
        blockers: list[Blocker] = []

        if not cascade and cascade_actions:
            blockers.append(
                Blocker(
                    code="HasDependentActions",
                    node_id=target.id,
                    detail="Есть зависимые действия; включите cascade",
                    chain=[a.id for a in cascade_actions],
                )
            )

        for node in revert_nodes:
            comp = self._compensator(node.action_type)
            if comp is None:
                blockers.append(
                    Blocker(
                        code="NotAllowed",
                        node_id=node.id,
                        detail=f"нет компенсатора для action_type={node.action_type}",
                    )
                )
                continue
            check = await comp.check(db, node.ref_id if node.ref_id is not None else -1)
            if not check.ok:
                for detail in check.blockers:
                    blockers.append(
                        Blocker(
                            code="CoverageShortfall" if check.deficit else "AlreadyReversed",
                            node_id=node.id,
                            detail=detail,
                            deficit=check.deficit,
                        )
                    )

        token = _sign_payload(
            {
                "action_id": action_id,
                "cascade": cascade,
                "fp": await self._fingerprint(db, [n.id for n in revert_nodes]),
            }
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

        order = self._reverse_topological_order([n.id for n in fresh_preview.revert],
                                                await self._deps_index(db))
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
            check = await comp.check(db, node.ref_id if node.ref_id is not None else -1)
            if not check.ok and check.deficit:
                raise CoverageShortfall(node=node.id, deficit=check.deficit)
            plan: ReversalPlan = await comp.plan(
                db, node.ref_id if node.ref_id is not None else -1, hard=False
            )
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
            reversal_action_id=reversal_action_ids[-1] if reversal_action_ids else 0,
            compensated_tx_ids=compensated_tx_ids,
            reversed_action_ids=reversed_action_ids,
        )

    # ── вспомогательное ──────────────────────────────────────────────────

    @staticmethod
    def _raise_blockers(blockers: list[Blocker]) -> None:
        for b in blockers:
            if b.code == "HasDependentActions":
                raise HasDependentActions(chain=list(b.chain or []))
            if b.code == "CoverageShortfall":
                raise CoverageShortfall(node=b.node_id or -1, deficit=b.deficit or Decimal("0"))
            if b.code == "NotAllowed":
                raise NotAllowed(b.detail)
            if b.code == "AlreadyReversed":
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
