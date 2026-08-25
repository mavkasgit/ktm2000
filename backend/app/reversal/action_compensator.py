"""StockActionCompensator — универсальный компенсатор доменных действий
(ADR-0019, тикет #116, волна B).

Компенсирует ВСЕ активные проводки одного Action зеркально 1:1
(reverses_id, те же product/from/to/dims/quantity, локации перевёрнуты),
реюзая механику ``MirrorLedgerMixin`` из StockCompensator (#114).
Партионность не вводится (ADR-0019 п.4 — компенсация проводочная).

Регистрируется в ReversalService на все доменные action_type волны A,
кроме ``seed_demo`` (демо-сид обратной силы не имеет — решение 7 спеки:
попытка reverse вернёт NotAllowed «нет компенсатора»).

Ограничения v1 (решение 6 спеки): специфичных доменных запретов поверх
ядра НЕ добавляется — блокировки зависимых (HasDependentActions), покрытие
(coverage) и статусы обеспечивает ReversalService. Цепочка задачи v1
строится только по ref_id=task.id (TASK_ACTION_FAMILY); между задачами
связей нет.

Реплей (#121): ``build_replay_payload`` извлекает координаты прямых
проводок действия (ledger) — payload для будущего слепого повтора
через доменные сервисы (отдельный тикет apply_forward).
"""
from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.action_journal import Action, ActionStatus
from app.reversal.base import (
    CheckBlocker,
    ReversalCheck,
    ReversalPlan,
    ReversalResult,
)
from app.reversal.stock_compensator import MirrorLedgerMixin
from app.stock.services import StockCommandService

# Доменные action_type с компенсатором (всё из решения 2 спеки, кроме
# seed_demo). transfer_* покрыты отдельным StockCompensator.
ACTION_COMPENSABLE_TYPES: frozenset[str] = frozenset({
    "task_complete",
    "final_release",
    "defect_decision",
    "return_to_stock",
    "manual_adjustment",
    "import_remainders",
    "plan_auto_release",
})


def _enum_str(val: object) -> str:
    """Извлечь .value у Enum или str() для прочего (JSON-safe сериализация)."""
    return val.value if hasattr(val, "value") else str(val)


class StockActionCompensator(MirrorLedgerMixin):
    """Компенсатор доменных действий журнала: план зеркальных проводок.

    Один экземпляр на action_type; действие разрешается по id узла
    (``action_id``, передаётся ядром) либо по паре (action_type, ref_id)
    при прямых вызовах. Для действий без ref_id (manual_adjustment) пара
    неоднозначна — ядро всегда передаёт action_id.
    """

    ACTION_TYPES = ACTION_COMPENSABLE_TYPES

    def __init__(self, action_type: str, command_service: StockCommandService | None = None):
        if action_type not in ACTION_COMPENSABLE_TYPES:
            raise ValueError(
                f"StockActionCompensator не покрывает action_type={action_type!r}"
            )
        self.action_type = action_type
        self._commands = command_service or StockCommandService()

    async def _get_action(
        self, db: AsyncSession, ref_id: int | None, action_id: int | None = None
    ) -> Action | None:
        if action_id is not None:
            action = await db.get(Action, action_id)
            if action is not None and action.action_type != self.action_type:
                return None
            return action
        if ref_id is None:
            # Без action_id действия с ref_id=NULL (manual_adjustment)
            # неоднозначны — честный not_found вместо угадывания.
            return None
        matches = (await db.execute(
            select(Action).where(
                Action.action_type == self.action_type,
                Action.ref_id == ref_id,
            )
        )).scalars().all()
        active = [a for a in matches if a.status == ActionStatus.ACTIVE]
        # Без action_id узел выбирается по (action_type, ref_id) только если
        # активное действие ровно одно; иначе неоднозначно — not_found
        # вместо тихой выборки order_by(id).limit(1).
        return active[0] if len(active) == 1 else None

    async def check(
        self, db: AsyncSession, ref_id: int | None, *, action_id: int | None = None
    ) -> ReversalCheck:
        action = await self._get_action(db, ref_id, action_id)
        if action is None:
            detail = (
                f"{self.action_type}: действие не найдено"
                + (f" по ref_id={ref_id}" if ref_id is not None else "")
            )
            return ReversalCheck(
                node_id=None, ok=False, blockers=[CheckBlocker(kind="not_found", detail=detail)]
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

    async def plan(
        self,
        db: AsyncSession,
        ref_id: int | None,
        *,
        hard: bool,
        action_id: int | None = None,
    ) -> ReversalPlan:
        action = await self._get_action(db, ref_id, action_id)
        if action is None:
            raise ValueError(f"{self.action_type}: действие для плана отката не найдено")
        entries = await self._plan_entries(db, action)
        return ReversalPlan(
            action_id=action.id,
            action_type=self.action_type,
            ref_id=action.ref_id,
            hard=hard,
            entries=entries,
        )

    async def apply(self, db: AsyncSession, plan: ReversalPlan, actor: str) -> ReversalResult:
        compensated = await self._apply_entries(db, plan, actor)
        return ReversalResult(
            action_id=plan.action_id,
            reversal_action_id=plan.reversal_action_id,
            compensated_tx_ids=compensated,
        )

    # ─── Replay (тикет #122): payload из координат проводок ──────────────

    async def build_replay_payload(
        self, db: AsyncSession, action: Action
    ) -> dict | None:
        """Payload реплея доменного действия (#122) из координат проводок.

        Возвращает список транзакций-координат действия — данные для
        будущего слепого повтора через доменные сервисы (отдельный
        тикет apply_forward). Компенсации предшественника под тем же
        action_id (amend #115) координатами не являются.

        Структура payload: ``{"entries": [<tx_coord>, …]}`` — каждая
        запись содержит product/from/to/quantity/reason/dimensions/quality
        и опциональные task_id, section_plan_line_id, is_post_factum.
        """
        txs = await self._generation(db, action)
        if not txs:
            return None
        entries: list[dict] = []
        for tx in txs:
            entry: dict = {
                "product_id": int(tx.product_id),
                "from_location_id": int(tx.from_location_id) if tx.from_location_id else None,
                "to_location_id": int(tx.to_location_id) if tx.to_location_id else None,
                "quantity": str(tx.quantity),
                "reason": _enum_str(tx.reason),
                "from_quality_state": _enum_str(tx.from_quality_state),
                "to_quality_state": _enum_str(tx.to_quality_state),
                "dimensions": dict(tx.dimensions) if tx.dimensions is not None else None,
            }
            if tx.task_id is not None:
                entry["task_id"] = int(tx.task_id)
            if tx.section_plan_line_id is not None:
                entry["section_plan_line_id"] = int(tx.section_plan_line_id)
            if tx.is_post_factum:
                entry["is_post_factum"] = True
            entries.append(entry)
        return {"entries": entries}
