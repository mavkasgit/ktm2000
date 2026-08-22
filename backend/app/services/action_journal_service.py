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
    ) -> Action:
        """Создать одну запись журнала действий и вернуть её."""
        action = Action(action_type=action_type, ref_id=ref_id, actor=actor)
        db.add(action)
        await db.flush()  # получить action.id для проводок операции
        return action


action_journal_service = ActionJournalService()
