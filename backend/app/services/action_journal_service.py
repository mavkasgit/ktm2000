"""Журналирование обратимых доменных действий (ADR-0019, тикет #113).

Минимальный контур: одна доменная операция = одна запись ``Action`` в
``action_journal``. Проводки ledger, порождённые операцией, получают
одинаковый ``action_id`` (через ``StockCommand.action_id``). Откат,
зависимости (``depends_on``) и каскад — тикеты #114+.
"""
from __future__ import annotations

from sqlalchemy.ext.asyncio import AsyncSession

from app.models.action_journal import Action


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


action_journal_service = ActionJournalService()
