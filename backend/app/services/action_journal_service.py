"""Журналирование обратимых доменных действий (ADR-0019, тикет #113).

Минимальный контур: одна доменная операция = одна запись ``Action`` в
``action_journal``. Проводки ledger, порождённые операцией, получают
одинаковый ``action_id`` (через ``StockCommand.action_id``). Откат,
зависимости (``depends_on``) и каскад — тикеты #114+.
"""
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.action_journal import Action, ActionStatus

# Семейство action_type с ref_id=task.id — участники depends_on-цепочки
# задачи (решение 3 спеки #116). v1: связи ставятся только внутри одной
# задачи (между задачами и для ref_id≠task.id, напр. defect_decision,
# цепочка не строится).
TASK_ACTION_FAMILY: frozenset[str] = frozenset({
    "task_complete",
    "final_release",
    "return_to_stock",
    "plan_auto_release",
})


class ActionJournalService:
    """Единая точка создания записей журнала действий."""

    async def log(
        self,
        db: AsyncSession,
        *,
        action_type: str,
        ref_id: int | None = None,
        actor: str | None = None,
        depends_on: list[int] | None = None,
        amends_action_id: int | None = None,
    ) -> Action:
        """Создать одну запись журнала действий и вернуть её.

        ``depends_on`` — зависимости (топологический порядок каскада);
        ``amends_action_id`` — связь «изменение → исходное действие»
        (ADR-0019, тикет #115): новое действие заменяет старое за один шаг.
        """
        action = Action(
            action_type=action_type,
            ref_id=ref_id,
            actor=actor,
            depends_on=list(depends_on or []),
            amends_action_id=amends_action_id,
        )
        db.add(action)
        await db.flush()  # получить action.id для проводок операции
        return action



    async def last_active_for_ref(
        self,
        db: AsyncSession,
        *,
        ref_id: int,
        action_types: frozenset[str] | set[str] | None = None,
    ) -> Action | None:
        """Последнее незакрытое (active) действие по ref_id.

        Используется для depends_on-цепочки задачи: каждое новое действие
        по задаче X зависит от последнего узла цепочки. Ограничение v1:
        связи только внутри одной задачи; между задачами не ставятся.
        """
        stmt = (
            select(Action)
            .where(
                Action.ref_id == ref_id,
                Action.status == ActionStatus.ACTIVE,
                Action.action_type.in_(action_types or TASK_ACTION_FAMILY),
            )
            .order_by(Action.id.desc())
            .limit(1)
        )
        return (await db.scalars(stmt)).first()

    async def log_task_action(
        self,
        db: AsyncSession,
        *,
        action_type: str,
        ref_id: int,
        actor: str | None = None,
    ) -> Action:
        """log() с автоматической depends_on-цепочкой задачи (решение 3)."""
        previous = await self.last_active_for_ref(db, ref_id=ref_id)
        return await self.log(
            db,
            action_type=action_type,
            ref_id=ref_id,
            actor=actor,
            depends_on=[previous.id] if previous is not None else [],
        )


action_journal_service = ActionJournalService()
