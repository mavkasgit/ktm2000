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
from app.reversal.base import (
    PlannedEntry,
    ReversalCheck,
    ReversalPlan,
    ReversalResult,
)
from app.stock.models import QualityState, StockBalance, StockTransaction
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

    async def check(self, db: AsyncSession, ref_id: int) -> ReversalCheck:
        action = await self._get_action(db, ref_id)
        if action is None:
            return ReversalCheck(node_id=-1, ok=False, blockers=["действие не найдено в журнале"])
        if action.status != ActionStatus.ACTIVE:
            return ReversalCheck(
                node_id=action.id, ok=False, blockers=[f"действие уже в статусе {action.status.value}"]
            )
        entries = await self._plan_entries(db, action)
        deficit = await self._coverage_deficit(db, entries)
        if deficit > 0:
            return ReversalCheck(
                node_id=action.id,
                ok=False,
                blockers=["недостаточно покрытия на складе для отката"],
                deficit=deficit,
            )
        return ReversalCheck(node_id=action.id, ok=True)

    async def plan(self, db: AsyncSession, ref_id: int, *, hard: bool) -> ReversalPlan:
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
                    section_plan_line_id=orig.section_plan_line_id,
                    is_post_factum=orig.is_post_factum,
                    created_by=orig.created_by,
                )
            )
        return entries

    async def _coverage_deficit(
        self, db: AsyncSession, entries: list[PlannedEntry]
    ) -> Decimal:
        """Дефицит покрытия: суммарный остаток, которого не хватает на
        складах-источниках компенсаций. Остаток ≥ 0 до и после — инвариант.
        Учётные проводки без геометрии (TRANSFER_RECEIVE) движения не дают
        и покрытия не требуют."""
        need: dict[tuple[int, int, QualityState, object], Decimal] = {}
        dims_by_key: dict[object, dict | None] = {}
        for e in entries:
            if e.from_location_id is None:
                continue
            key = (e.product_id, e.from_location_id, e.quality_state, _dims_key(e.dimensions))
            dims_by_key.setdefault(_dims_key(e.dimensions), e.dimensions)
            need[key] = need.get(key, Decimal("0")) + e.quantity

        deficit = Decimal("0")
        for (product_id, location_id, qs, dk), qty in need.items():
            available_q = (
                select(func.coalesce(func.sum(StockBalance.balance_qty), 0)).where(
                    StockBalance.location_id == location_id,
                    StockBalance.product_id == product_id,
                    StockBalance.quality_state == qs,
                    StockBalance.balance_qty > 0,
                    dimensions_match_clause(StockBalance.dimensions, dims_by_key.get(dk)),
                )
            )
            available = (await db.scalar(available_q)) or Decimal("0")
            if available < qty:
                deficit += qty - available
        return deficit

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
                        f"reversal:{plan.reversal_action_id}:tx:{entry.source_tx_id}"
                    ),
                    is_post_factum=entry.is_post_factum,
                ),
            )
            compensated.append(tx.id)
        return ReversalResult(
            action_id=plan.action_id,
            reversal_action_id=plan.reversal_action_id,
            compensated_tx_ids=compensated,
        )


def _dims_key(dims: dict | None) -> tuple | None:
    if dims is None:
        return None
    return tuple(sorted(dims.items()))
