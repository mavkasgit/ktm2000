"""Модель универсального журнала действий (ADR-0019, эпик Reversal).

``Action`` — единая запись обратимого доменного действия (передача,
завершение, брак, импорт остатков, план). Доменная сущность ссылается на
запись журнала через ``ref_id``; проводки ledger, порождённые действием,
несут ``stock_transactions.action_id``. Откат — только компенсирующими
записями (append-only), связанными с исходными через
``stock_transactions.reverses_id``.
"""
from __future__ import annotations

from datetime import datetime

from sqlalchemy import (
    BigInteger,
    DateTime,
    ForeignKey,
    Identity,
    String,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base


class Action(Base):
    """Единый журнал обратимых действий (ADR-0019).

    Одна доменная операция = одна запись. ``depends_on`` — JSON-массив id
    действий, от которых зависит данное (топологический порядок каскада).
    ``reversed_by_action_id`` / ``amends_action_id`` — связи отката и
    поправки внутри самого журнала.
    """

    __tablename__ = "action_journal"

    id: Mapped[int] = mapped_column(
        BigInteger, Identity(always=True), primary_key=True, autoincrement=True
    )
    action_type: Mapped[str] = mapped_column(String(50), nullable=False)
    ref_id: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    actor: Mapped[str | None] = mapped_column(String(120), nullable=True)
    status: Mapped[str] = mapped_column(
        String(20), nullable=False, server_default=text("'active'"), default="active"
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
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
