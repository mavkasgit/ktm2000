"""Модель универсального журнала действий (ADR-0019, эпик Reversal).

``Action`` — единая запись обратимого доменного действия (передача,
завершение, брак, импорт остатков, план). Доменная сущность ссылается на
запись журнала через ``ref_id``; проводки ledger, порождённые действием,
несут ``stock_transactions.action_id``. Откат — только компенсирующими
записями (append-only), связанными с исходными через
``stock_transactions.reverses_id``.
"""
from __future__ import annotations

import enum
from datetime import datetime

from sqlalchemy import (
    BigInteger,
    CheckConstraint,
    Enum,
    DateTime,
    ForeignKey,
    Identity,
    String,
    Text,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base


class ActionStatus(str, enum.Enum):
    """Статус действия в журнале (ADR-0019 п.8)."""

    ACTIVE = "active"
    REVERSED = "reversed"
    AMENDED = "amended"
    PURGED = "purged"  # hard-чистка скомпенсированных пар (#118)


class Action(Base):
    """Единый журнал обратимых действий (ADR-0019).

    Одна доменная операция = одна запись. ``depends_on`` — JSON-массив id
    действий, от которых зависит данное (топологический порядок каскада).
    ``reversed_by_action_id`` / ``amends_action_id`` — связи отката и
    поправки внутри самого журнала.
    """

    __tablename__ = "action_journal"
    __table_args__ = (
        CheckConstraint(
            "status IN ('active', 'reversed', 'amended', 'purged')",
            name="ck_action_journal_status",
        ),
    )

    id: Mapped[int] = mapped_column(
        BigInteger, Identity(always=True), primary_key=True, autoincrement=True
    )
    action_type: Mapped[str] = mapped_column(String(50), nullable=False, index=True)
    ref_id: Mapped[int | None] = mapped_column(BigInteger, nullable=True, index=True)
    actor: Mapped[str | None] = mapped_column(String(120), nullable=True)
    status: Mapped[ActionStatus] = mapped_column(
        Enum(
            ActionStatus,
            name="action_status",
            native_enum=False,
            values_callable=lambda x: [e.value for e in x],
        ),
        nullable=False,
        server_default=text("'active'"),
        default=ActionStatus.ACTIVE,
    )
    depends_on: Mapped[list] = mapped_column(
        JSONB, nullable=False, server_default=text("'[]'"), default=list
    )
    reversed_by_action_id: Mapped[int | None] = mapped_column(
        ForeignKey("action_journal.id"), nullable=True
    )
    amends_action_id: Mapped[int | None] = mapped_column(
        ForeignKey("action_journal.id"), nullable=True
    )
    reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
