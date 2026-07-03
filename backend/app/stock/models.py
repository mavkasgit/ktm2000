"""Модели домена Stock Ledger.

Локации — это секции (``Section``) с единым классификатором ``Section.type``
(String(20), 6 значений: ``production | raw_stock | wip_stock | finished_stock | scrap | quarantine``).
Отдельной таблицы Location нет: станки и склады — это Section, различаются по ``type``.
Поле ``kind`` и enum ``LocationType`` удалены в эпике section-cleanup (миграция 027).

``StockTransaction`` — единый append-only ledger, заменяющий ``Movement``.
Запись хранит явное перемещение ``from_location_id → to_location_id`` (оба
nullable для ручных приходов/расходов из ниоткуда) с причиной ``reason`` и
состоянием качества ``quality_state``.

``StockBalance`` — материализованный кэш баланса по ключу
``(product_id, location_id, quality_state)``. Пересчитывается из
``StockTransaction`` через ``StockProjectionManager``. Не бизнес-сущность.
"""
from __future__ import annotations

import enum
from datetime import datetime
from decimal import Decimal

from sqlalchemy import (
    BigInteger,
    Boolean,
    CheckConstraint,
    DateTime,
    Enum,
    ForeignKey,
    Identity,
    Numeric,
    String,
    Text,
    UniqueConstraint,
    func,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base


class Reason(str, enum.Enum):
    """Причина движения материала в ledger.

    Каждая причина однозначно интерпретируется без знаковой магии:
    ``from_location → to_location`` всегда показывает, откуда и куда
    переместился материал. Не зависит от знака количества (quantity > 0
    всегда).
    """

    ISSUE_TO_WORK = "issue_to_work"  # RAW_STOCK → production
    COMPLETE = "complete"  # production → WIP_STOCK/FINISHED_STOCK (good output)
    TRANSFER_SEND = "transfer_send"  # from_task.location → TRANSIT (or to_task.location)
    TRANSFER_RECEIVE = "transfer_receive"  # TRANSIT (or from_task.location) → to_task.location
    RETURN_TO_STOCK = "return_to_stock"  # production → RAW_STOCK (unused material)
    RETURN_TO_PREVIOUS = "return_to_previous"  # → previous location (defect decision)
    FINAL_RELEASE = "final_release"  # WIP_STOCK → FINISHED_STOCK
    SCRAP = "scrap"  # any → SCRAP, quality_state=SCRAP
    REWORK = "rework"  # any → REWORK location, quality_state=REWORK
    QUARANTINE = "quarantine"  # any → QUARANTINE location, quality_state=QUARANTINE (hold decision)
    ADJUSTMENT_IN = "adjustment_in"  # manual stock count correction (+)
    ADJUSTMENT_OUT = "adjustment_out"  # manual stock count correction (-)
    MANUAL_IN = "manual_in"  # external supply → stock
    MANUAL_OUT = "manual_out"  # stock → external (write-off)


class QualityState(str, enum.Enum):
    """Состояние качества материала в конкретной транзакции/балансе.

    Баланс считается по ключу ``(product, location, quality_state)`` — то
    есть 10 годных и 3 в переделке на одной полке — это две разные строки
    ``StockBalance``. Это позволяет убрать отдельные таблицы для брака и
    переделки: брак = движение ``quality_state=SCRAP`` в ``SCRAP`` локацию.
    """

    GOOD = "good"
    SCRAP = "scrap"
    REWORK = "rework"
    QUARANTINE = "quarantine"


class StockTransaction(Base):
    """Единый append-only ledger всех движений материала.

    Источник правды для баланса и для аудита. Никогда не мутируется и не
    удаляется: отмена = компенсационная транзакция с ``reason`` исходной.
    """

    __tablename__ = "stock_transactions"
    __table_args__ = (
        CheckConstraint("quantity > 0", name="ck_stock_transactions_quantity_positive"),
        CheckConstraint(
            "(from_location_id IS NOT NULL) OR (to_location_id IS NOT NULL)",
            name="ck_stock_transactions_at_least_one_location",
        ),
        CheckConstraint(
            "from_location_id IS NULL OR to_location_id IS NULL OR from_location_id <> to_location_id",
            name="ck_stock_transactions_locations_differ",
        ),
    )

    id: Mapped[int] = mapped_column(
        BigInteger, Identity(always=True), primary_key=True, autoincrement=True
    )
    product_id: Mapped[int] = mapped_column(ForeignKey("products.id"), nullable=False, index=True)
    from_location_id: Mapped[int | None] = mapped_column(
        ForeignKey("sections.id"), nullable=True, index=True
    )
    to_location_id: Mapped[int | None] = mapped_column(
        ForeignKey("sections.id"), nullable=True, index=True
    )
    quantity: Mapped[Decimal] = mapped_column(Numeric(14, 3), nullable=False)
    reason: Mapped[Reason] = mapped_column(
        Enum(Reason, name="stock_reason", values_callable=lambda x: [e.value for e in x]),
        nullable=False, index=True,
    )
    # Качество материала на исходной стороне (до перехода).
    # Для SCRAP/REWORK: from_quality_state=good, to_quality_state=scrap/rework.
    # Для перемещения уже-брака: from_quality_state=scrap, to_quality_state=scrap.
    from_quality_state: Mapped[QualityState] = mapped_column(
        Enum(QualityState, name="stock_quality_state", values_callable=lambda x: [e.value for e in x]),
        nullable=False,
        server_default=text("'good'"),
        default=QualityState.GOOD,
        index=True,
    )
    to_quality_state: Mapped[QualityState] = mapped_column(
        Enum(QualityState, name="stock_quality_state", create_type=False, values_callable=lambda x: [e.value for e in x]),
        nullable=False,
        server_default=text("'good'"),
        default=QualityState.GOOD,
        index=True,
    )
    task_id: Mapped[int | None] = mapped_column(
        ForeignKey("work_tasks.id"), nullable=True, index=True
    )
    transfer_id: Mapped[int | None] = mapped_column(
        ForeignKey("transfers.id"), nullable=True, index=True
    )
    section_plan_line_id: Mapped[int | None] = mapped_column(
        ForeignKey("section_plan_lines.id"), nullable=True
    )
    # Compensates: id исходной транзакции, если эта — компенсационная (cancel/correct)
    compensates_tx_id: Mapped[int | None] = mapped_column(
        ForeignKey("stock_transactions.id"), nullable=True
    )
    source_ref: Mapped[str | None] = mapped_column(String(255), nullable=True)
    idempotency_key: Mapped[str | None] = mapped_column(String(128), nullable=True, index=True)
    comment: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_by: Mapped[int] = mapped_column(ForeignKey("users.id"), nullable=False)
    executor_user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    created_by_user_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    executor_user_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    performed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    accounted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    is_post_factum: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default=text("false"), default=False
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


class StockBalance(Base):
    """Материализованный кэш баланса по ``(product, location, quality_state)``.

    Не источник правды — пересчитывается из ``StockTransaction`` через
    ``StockProjectionManager.refresh_balance``. Существует только для
    производительности чтения (баланс по SKU за O(1) вместо SUM по ledger).
    """

    __tablename__ = "stock_balances"
    __table_args__ = (
        UniqueConstraint(
            "product_id",
            "location_id",
            "quality_state",
            name="uq_stock_balances_product_location_quality",
        ),
        CheckConstraint("balance_qty <> 0", name="ck_stock_balances_nonzero"),
    )

    id: Mapped[int] = mapped_column(
        BigInteger, Identity(always=True), primary_key=True, autoincrement=True
    )
    product_id: Mapped[int] = mapped_column(ForeignKey("products.id"), nullable=False, index=True)
    location_id: Mapped[int] = mapped_column(ForeignKey("sections.id"), nullable=False, index=True)
    quality_state: Mapped[QualityState] = mapped_column(
        Enum(QualityState, name="stock_quality_state", values_callable=lambda x: [e.value for e in x]),
        nullable=False,
        server_default=text("'good'"),
        default=QualityState.GOOD,
    )
    balance_qty: Mapped[Decimal] = mapped_column(Numeric(14, 3), nullable=False, default=0)
    refreshed_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
