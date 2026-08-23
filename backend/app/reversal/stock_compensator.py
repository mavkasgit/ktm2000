"""StockCompensator — первый доменный компенсатор (ADR-0019, тикет #114).

Покрывает стоковые действия ``transfer_send`` и ``transfer_cancel``
(``ref_id`` = id Transfer). Откат — зеркальные проводки 1:1 (те же
product/from/to/dimensions/quantity, локации перевёрнуты,
``reverses_id`` = исходная проводка), без партионности (ADR-0001).
"""
from __future__ import annotations

from decimal import Decimal

from sqlalchemy import exists, func, select
from sqlalchemy.orm import aliased
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.action_journal import Action, ActionStatus
from app.models.transfer import Transfer, TransferStatus
from app.reversal.base import (
    CheckBlocker,
    PlannedEntry,
    ReversalCheck,
    ReversalPlan,
    ReversalResult,
)
from app.stock.models import QualityState, Reason, StockBalance, StockTransaction
from app.stock.services import StockCommand, StockCommandService, dimensions_match_clause

_STOCK_ACTION_TYPES = ("transfer_send", "transfer_cancel")


class StockCompensator:
    """Компенсатор стоковых действий: план зеркальных проводок + исполнение."""

    def __init__(self, action_type: str, command_service: StockCommandService | None = None):
        if action_type not in _STOCK_ACTION_TYPES:
            raise ValueError(f"StockCompensator не покрывает action_type={action_type!r}")
        self.action_type = action_type
        self._commands = command_service or StockCommandService()

    async def _get_action(self, db: AsyncSession, ref_id: int) -> Action | None:
        return (
            await db.execute(
                select(Action)
                .where(
                    Action.action_type == self.action_type,
                    Action.ref_id == ref_id,
                )
                .order_by(Action.id.asc())
                .limit(1)
            )
        ).scalar_one_or_none()

    @staticmethod
    async def _generation(db: AsyncSession, action: Action):
        """Проводки действия, ещё не погашенные компенсациями."""
        comp = aliased(StockTransaction, name="comp")
        not_reversed = ~exists(
            select(comp.id).where(comp.reverses_id == StockTransaction.id)
        )
        return (
            await db.execute(
                select(StockTransaction)
                .where(StockTransaction.action_id == action.id, not_reversed)
                .order_by(StockTransaction.id.asc())
            )
        ).scalars().all()

    async def check(self, db: AsyncSession, ref_id: int | None) -> ReversalCheck:
        if ref_id is None:
            return ReversalCheck(
                node_id=None,
                ok=False,
                blockers=[CheckBlocker(kind="not_found", detail="у действия нет ref_id")],
            )
        action = await self._get_action(db, ref_id)
        if action is None:
            return ReversalCheck(
                node_id=None,
                ok=False,
                blockers=[
                    CheckBlocker(
                        kind="not_found",
                        detail=f"{self.action_type}: действие с ref_id={ref_id} не найдено",
                    )
                ],
            )
        if action.status != ActionStatus.ACTIVE:
            return ReversalCheck(
                node_id=action.id,
                ok=False,
                blockers=[
                    CheckBlocker(
                        kind="already_reversed",
                        detail=f"действие уже в статусе {action.status.value}",
                    )
                ],
            )
        # Доменно-отменённое действие: Transfer отменён через cancel_transfer
        # (запись журнала при этом остаётся active). Preview-first: блокер
        # already_reversed, confirm невозможен до повторного preview.
        transfer = await db.get(Transfer, ref_id)
        if transfer is not None and transfer.status == TransferStatus.cancelled:
            return ReversalCheck(
                node_id=action.id,
                ok=False,
                blockers=[
                    CheckBlocker(
                        kind="already_reversed",
                        detail=f"передача #{ref_id} уже отменена в домене (status=cancelled)",
                    )
                ],
            )
        entries = await self._plan_entries(db, action)
        deficit = await self._coverage_deficit(db, entries)
        if deficit > 0:
            return ReversalCheck(
                node_id=action.id,
                ok=False,
                blockers=[
                    CheckBlocker(
                        kind="coverage",
                        detail="недостаточно покрытия на складе для отката",
                        deficit=deficit,
                    )
                ],
                deficit=deficit,
            )
        return ReversalCheck(node_id=action.id, ok=True)

    async def plan(self, db: AsyncSession, ref_id: int | None, *, hard: bool) -> ReversalPlan:
        if ref_id is None:
            raise ValueError(f"{self.action_type}: у действия нет ref_id")
        action = await self._get_action(db, ref_id)
        if action is None:
            raise ValueError(f"{self.action_type}: действие с ref_id={ref_id} не найдено")
        entries = await self._plan_entries(db, action)
        return ReversalPlan(
            action_id=action.id,
            action_type=self.action_type,
            ref_id=ref_id,
            hard=hard,
            entries=entries,
        )

    async def _plan_entries(
        self, db: AsyncSession, action: Action
    ) -> list[PlannedEntry]:
        originals = await self._generation(db, action)
        entries: list[PlannedEntry] = []
        for orig in originals:
            # Переворот локаций: исходная приёмная сторона становится источником.
            entries.append(
                PlannedEntry(
                    source_tx_id=orig.id,
                    product_id=orig.product_id,
                    from_location_id=orig.to_location_id,
                    to_location_id=orig.from_location_id,
                    quantity=orig.quantity,
                    dimensions=orig.dimensions,
                    reason=orig.reason,
                    quality_state=orig.from_quality_state,
                    to_quality_state=orig.to_quality_state,
                    task_id=orig.task_id,
                    transfer_id=orig.transfer_id,
                    section_plan_line_id=orig.section_plan_line_id,
                    is_post_factum=orig.is_post_factum,
                    created_by=orig.created_by,
                )
            )
        return entries

    @staticmethod
    def _coverage_needs(
        entries: list[PlannedEntry],
    ) -> tuple[dict[tuple[int, int, QualityState, object], Decimal], dict[object, dict | None]]:
        """Потребности покрытий по ключу (product, location, quality, dims)."""
        need: dict[tuple[int, int, QualityState, object], Decimal] = {}
        dims_by_key: dict[object, dict | None] = {}
        for e in entries:
            if e.from_location_id is None:
                continue
            key = (e.product_id, e.from_location_id, e.quality_state, _dims_key(e.dimensions))
            dims_by_key.setdefault(_dims_key(e.dimensions), e.dimensions)
            need[key] = need.get(key, Decimal("0")) + e.quantity
        return need, dims_by_key

    async def _deficit_for(
        self,
        db: AsyncSession,
        need: dict[tuple[int, int, QualityState, object], Decimal],
        dims_by_key: dict[object, dict | None],
        *,
        adjustments: dict[tuple[int, int, QualityState, object], Decimal] | None = None,
    ) -> Decimal:
        """Дефицит по потребностям против текущих остатков; ``adjustments``
        — чистовый эффект ещё не применённых проводок на ключ (+приход /
        −расход), например компенсаций в preview_amend (D7-A)."""
        deficit = Decimal("0")
        for key, qty in need.items():
            product_id, location_id, qs, dk = key
            available_q = (
                select(func.coalesce(func.sum(StockBalance.balance_qty), 0)).where(
                    StockBalance.location_id == location_id,
                    StockBalance.product_id == product_id,
                    StockBalance.quality_state == qs,
                    StockBalance.balance_qty > 0,
                    dimensions_match_clause(StockBalance.dimensions, dims_by_key.get(dk)),
                )
            )
            available = ((await db.scalar(available_q)) or Decimal("0")) + (
                (adjustments or {}).get(key, Decimal("0"))
            )
            if available < qty:
                deficit += qty - available
        return deficit

    async def _coverage_deficit(
        self, db: AsyncSession, entries: list[PlannedEntry]
    ) -> Decimal:
        """Дефицит покрытия: суммарный остаток, которого не хватает на
        складах-источниках компенсаций. Остаток ≥ 0 до и после — инвариант.
        Учётные проводки без геометрии (TRANSFER_RECEIVE) движения не дают
        и покрытия не требуют."""
        need, dims_by_key = self._coverage_needs(entries)
        return await self._deficit_for(db, need, dims_by_key)

    async def apply(self, db: AsyncSession, plan: ReversalPlan, actor: str) -> ReversalResult:
        if plan.reversal_action_id is None:
            raise ValueError("plan.reversal_action_id не проставлен ReversalService")
        comment = plan.comment or f"reversal of action #{plan.action_id}"
        compensated: list[int] = []
        for entry in plan.entries:
            tx = await self._commands.record(
                db,
                StockCommand(
                    product_id=entry.product_id,
                    quantity=entry.quantity,
                    reason=entry.reason,
                    from_location_id=entry.from_location_id,
                    to_location_id=entry.to_location_id,
                    dimensions=entry.dimensions,
                    quality_state=entry.quality_state,
                    to_quality_state=entry.to_quality_state,
                    task_id=entry.task_id,
                    transfer_id=entry.transfer_id,
                    section_plan_line_id=entry.section_plan_line_id,
                    reverses_id=entry.source_tx_id,
                    action_id=plan.reversal_action_id,
                    created_by=plan.actor_id or entry.created_by,
                    created_by_user_name=actor,
                    comment=f"{comment} [tx #{entry.source_tx_id}]",
                    idempotency_key=(
                        f"{plan.idem_prefix}:{plan.reversal_action_id}:tx:{entry.source_tx_id}"
                    ),
                    is_post_factum=entry.is_post_factum,
                ),
            )
            compensated.append(tx.id)
        # Полная компенсация проводок передачи эквивалентна доменной отмене:
        # Transfer уходит в cancelled, иначе S6 (accepted ⇔ net == sent)
        # нарушается, а повторный preview честно блокируется по п.2.
        if plan.ref_id is not None:
            transfer = await db.get(Transfer, plan.ref_id)
            if transfer is not None and transfer.status == TransferStatus.accepted:
                transfer.status = TransferStatus.cancelled
                transfer.accepted_quantity = Decimal("0")
        return ReversalResult(
            action_id=plan.action_id,
            reversal_action_id=plan.reversal_action_id,
            compensated_tx_ids=compensated,
        )

    # ─── Amend (тикет #115): валидация payload + D7-A + новая запись ──────

    _AMEND_FIELDS = ("quantity", "from_task_id", "to_task_id", "dimensions")

    async def validate_amend_changes(
        self, db: AsyncSession, ref_id: int | None, changes: dict
    ) -> list[CheckBlocker]:
        """Валидация payload amend для transfer_send.

        Разрешённые поля: quantity / from_task_id / to_task_id / dimensions.
        Неизвестные поля, неположительное количество, несуществующие задачи
        или неканонизируемая геометрия — блокеры not_allowed (preview-first).
        """
        from app.domain.dimensions import canonicalize_dimensions
        from app.models.work_task import WorkTask

        blockers: list[CheckBlocker] = []
        if not isinstance(changes, dict) or not changes:
            return [
                CheckBlocker(kind="not_allowed", detail="пустой payload изменений")
            ]
        unknown = set(changes) - set(self._AMEND_FIELDS)
        if unknown:
            blockers.append(
                CheckBlocker(
                    kind="not_allowed",
                    detail=f"неизвестные поля изменений: {sorted(unknown)}",
                )
            )
        transfer = await db.get(Transfer, ref_id) if ref_id is not None else None
        if transfer is None:
            return blockers or [
                CheckBlocker(
                    kind="not_found",
                    detail=f"{self.action_type}: Transfer с ref_id={ref_id} не найден",
                )
            ]

        if "quantity" in changes:
            try:
                qty = Decimal(str(changes["quantity"]))
                if qty <= 0:
                    raise ArithmeticError("non-positive")
            except Exception:  # noqa: BLE001 — любая порча quantity = блокер
                blockers.append(
                    CheckBlocker(
                        kind="not_allowed",
                        detail=f"некорректное quantity: {changes['quantity']!r}",
                    )
                )
        for field in ("from_task_id", "to_task_id"):
            if field in changes:
                task = await db.get(WorkTask, int(changes[field]))
                if task is None:
                    blockers.append(
                        CheckBlocker(
                            kind="not_allowed",
                            detail=f"задача {field}={changes[field]} не найдена",
                        )
                    )
        if "dimensions" in changes and changes["dimensions"] is not None:
            try:
                canonicalize_dimensions(changes["dimensions"])
            except Exception as exc:  # noqa: BLE001
                blockers.append(
                    CheckBlocker(
                        kind="not_allowed",
                        detail=f"некорректная геометрия dimensions: {exc}",
                    )
                )
        return blockers

    async def forward_coverage_deficit(
        self,
        db: AsyncSession,
        ref_id: int | None,
        changes: dict,
        *,
        comp_entries: list[PlannedEntry] | None = None,
    ) -> Decimal:
        """D7-A: дефицит покрытия новой прямой проводки TRANSFER_SEND.

        Новая передача списывает склад-источник; если ``comp_entries``
        заданы (preview — компенсации ещё не применены), к доступному
        остатку добавляется их чистовый эффект на каждый ключ.
        """
        from app.domain.dimensions import canonicalize_dimensions
        from app.models.work_task import WorkTask

        transfer = await db.get(Transfer, ref_id) if ref_id is not None else None
        if transfer is None:
            return Decimal("0")
        product_id = transfer.product_id
        dims_raw = (
            changes.get("dimensions")
            if changes.get("dimensions") is not None
            else transfer.dimensions
        )
        dims = canonicalize_dimensions(dims_raw)
        from_task_id = changes.get("from_task_id", transfer.from_task_id)
        from_task = await db.get(WorkTask, int(from_task_id))
        if from_task is None:
            return Decimal("0")
        quantity = Decimal(str(changes.get("quantity", transfer.sent_quantity)))
        need_fwd: PlannedEntry = PlannedEntry(
            source_tx_id=0,
            product_id=product_id,
            from_location_id=from_task.section_id,
            to_location_id=None,
            quantity=quantity,
            dimensions=dims,
            reason=Reason.TRANSFER_SEND,
            quality_state=QualityState.GOOD,
        )
        need, dims_by_key = self._coverage_needs([need_fwd])
        adjustments: dict[tuple[int, int, QualityState, object], Decimal] = {}
        if comp_entries:
            comp_need, _ = self._coverage_needs(comp_entries)
            # Чистовый эффект компенсаций: −расход на своём from_location
            # и +приход на to_location (перевёрнутая геометрия).
            for key, qty in comp_need.items():
                adjustments[key] = adjustments.get(key, Decimal("0")) - qty
            for e in comp_entries:
                if e.to_location_id is None:
                    continue
                ckey = (
                    e.product_id,
                    e.to_location_id,
                    e.quality_state,
                    _dims_key(e.dimensions),
                )
                adjustments[ckey] = adjustments.get(ckey, Decimal("0")) + e.quantity
        return await self._deficit_for(db, need, dims_by_key, adjustments=adjustments)

    async def check_amend(
        self, db: AsyncSession, ref_id: int | None, changes: dict
    ) -> ReversalCheck:
        """Полная preflight-проверка amend: базовый check отката + валидация
        payload + покрытие новой прямой записи (с учётом компенсаций)."""
        base = await self.check(db, ref_id)
        if not base.ok:
            return base
        blockers = await self.validate_amend_changes(db, ref_id, changes)
        action = await self._get_action(db, ref_id)
        assert action is not None  # check() уже отфильтровал отсутствие
        comp_entries = await self._plan_entries(db, action)
        deficit = await self.forward_coverage_deficit(
            db, ref_id, changes, comp_entries=comp_entries
        )
        if deficit > 0:
            blockers.append(
                CheckBlocker(
                    kind="coverage",
                    detail="недостаточно покрытия для новой записи amend (D7-A)",
                    deficit=deficit,
                )
            )
        return ReversalCheck(
            node_id=action.id, ok=not blockers, blockers=blockers, deficit=deficit or None
        )

    async def apply_forward(
        self,
        db: AsyncSession,
        *,
        action,  # noqa: ANN001 — Action журнала (уже создан ReversalService)
        ref_id: int | None,
        changes: dict,
        actor: str,
        actor_id: int | None,
    ) -> dict:
        """Новая доменная запись (Transfer) + прямые проводки ledger.

        Реюз ``transfer_send`` — единственного write-path передачи: он
        создаёт Transfer, пару SEND/RECEIVE и проекции; проводки ссылаются
        на переданное действие журнала. Задачи по умолчанию наследуются от
        исходного Transfer (changes может переопределить). Идемпотентность
        по ключу ``amend:{action.id}`` (отличать от повторов отправки).
        """
        from app.transfers.services import transfer_send

        old_transfer = await db.get(Transfer, ref_id) if ref_id is not None else None
        if old_transfer is None:
            raise ValueError(f"{self.action_type}: Transfer с ref_id={ref_id} не найден")
        return await transfer_send(
            db,
            from_task_id=int(
                changes.get("from_task_id", old_transfer.from_task_id)
            ),
            to_task_id=(
                int(changes.get("to_task_id", old_transfer.to_task_id))
            ),
            quantity=Decimal(str(changes.get("quantity", old_transfer.sent_quantity))),
            dimensions=changes.get("dimensions"),
            actor_id=actor_id,
            comment=f"amend of action #{action.amends_action_id}",
            idempotency_key=f"amend:{action.id}",
            action=action,
        )

def _dims_key(dims: dict | None) -> tuple | None:
    if dims is None:
        return None
    return tuple(sorted(dims.items()))
