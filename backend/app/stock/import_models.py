"""Модели истории импорта остатков (ADR-0052, ADR-0053).

Реестр батчей импорта остатков. Отдельные таблицы, а не переиспользование
``import_batches``: там ``production_plan_id``, ``mode``, ``sheet_name``,
``header_row_number`` — ``NOT NULL`` и все про план. ``import_files``
переиспользуется как есть: он нейтрален (имя, путь, sha256, размер), и на
него ссылается только заголовок батча.

Ключевые отличия от плана, которые видны в схеме:

* **однофазность** (ADR-0052 п.2) — у батча нет состояний ``parsed``/``failed``;
  импорт остатков применяется сразу, поэтому статус только ``applied`` и
  ``rolled_back``;
* **откат зеркальными компенсациями** (п.3) — у строки нет ``before_data``:
  проводки откатываются зеркально по узлу журнала, а не восстановлением
  сохранённых значений. Единственное, что нужно помнить про состояние «до», —
  проводки фазы ``clear_existing``, и они лежат в ledger;
* **скрытие не статус** (п.5) — ``deleted_at`` ортогонально ``status``:
  скрытый батч может быть и откатанным, и нет.
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
    ForeignKey,
    Identity,
    Index,
    Integer,
    Numeric,
    String,
    Text,
    UniqueConstraint,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base


class StockImportBatchStatus(str, enum.Enum):
    """Статус батча импорта остатков (ADR-0052 п.2, п.5).

    ``parsed``/``failed`` планового ``ImportBatchStatus`` невозможны: импорт
    остатков однофазный, черновика нет. Скрытие из списка статусом **не**
    выражается — это ``deleted_at`` (п.5).
    """

    APPLIED = "applied"
    ROLLED_BACK = "rolled_back"


class StockImportRowStatus(str, enum.Enum):
    """Вердикт строки импорта: залита или пропущена с ошибками."""

    VALID = "valid"
    INVALID = "invalid"


class StockImportBatch(Base):
    """Батч импорта остатков — одна применённая операция импорта целиком.

    Ровно один узел журнала действий (``action_id``, ``import_remainders``) и
    ноль или больше :class:`StockImportRow`. Идентичность батча — узел журнала,
    поэтому на ``action_id`` стоит уникальный констрейнт: батч не может
    задвоиться, а узел журнала по ADR-0019 §7 не удаляется никогда.
    """

    __tablename__ = "stock_import_batches"
    __table_args__ = (
        CheckConstraint(
            "status IN ('applied', 'rolled_back')",
            name="ck_stock_import_batches_status",
        ),
        UniqueConstraint("action_id", name="uq_stock_import_batches_action_id"),
    )

    id: Mapped[int] = mapped_column(
        BigInteger, Identity(always=True), primary_key=True, autoincrement=True
    )
    action_id: Mapped[int] = mapped_column(
        ForeignKey("action_journal.id"), nullable=False
    )
    # NULL у legacy-батчей: склад импорта до миграции не сохранялся (п.7).
    file_id: Mapped[int | None] = mapped_column(
        ForeignKey("import_files.id"), nullable=True
    )
    location_id: Mapped[int | None] = mapped_column(
        ForeignKey("sections.id"), nullable=True, index=True
    )
    status: Mapped[StockImportBatchStatus] = mapped_column(
        String(20), nullable=False, server_default=text("'applied'"), default=StockImportBatchStatus.APPLIED, index=True
    )
    # Бэкфилл из action_journal (п.7): нет файла и нет строк импорта.
    legacy: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default=text("false"), default=False
    )
    clear_existing: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default=text("false"), default=False
    )
    sheet_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    total_rows: Mapped[int] = mapped_column(
        BigInteger, nullable=False, server_default=text("0"), default=0
    )
    imported_rows: Mapped[int] = mapped_column(
        BigInteger, nullable=False, server_default=text("0"), default=0
    )
    skipped_rows: Mapped[int] = mapped_column(
        BigInteger, nullable=False, server_default=text("0"), default=0
    )
    summary: Mapped[dict] = mapped_column(
        JSONB, nullable=False, server_default=text("'{}'::jsonb"), default=dict
    )
    created_by: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    created_by_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    rolled_back_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    rolled_back_by: Mapped[int | None] = mapped_column(
        ForeignKey("users.id"), nullable=True
    )
    # Мягкое удаление: спрятать запись из списка, ledger не трогать (п.5).
    deleted_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    deleted_by: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    delete_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(), index=True
    )


class StockImportRow(Base):
    """Строка импорта остатков — одна строка файла и её вердикт.

    ``stock_transaction_id`` — обязательная связь для залитой строки: при
    ``skip_invalid=True`` часть строк пропускается молча, и без ссылки на
    проводку нельзя ни объяснить пропуск, ни показать блокировку покрытия при
    откате (ADR-0052 п.8). ``raw_values`` — сырые значения файла: источник
    истины в споре «в файле было так, а залили так».

    ``before``-состояния здесь нет намеренно: откат идёт зеркальными
    компенсациями по узлу журнала, а не восстановлением значений (п.3).
    """

    __tablename__ = "stock_import_rows"
    __table_args__ = (
        CheckConstraint("status IN ('valid', 'invalid')", name="ck_stock_import_rows_status"),
        Index("ix_stock_import_rows_batch_id", "batch_id"),
    )

    id: Mapped[int] = mapped_column(
        BigInteger, Identity(always=True), primary_key=True, autoincrement=True
    )
    batch_id: Mapped[int] = mapped_column(
        ForeignKey("stock_import_batches.id"), nullable=False
    )
    source_row_number: Mapped[int] = mapped_column(Integer, nullable=False)
    sku: Mapped[str] = mapped_column(String(255), nullable=False, server_default=text("''"))
    # Что реально сопоставлено: частичное совпадение артикула допустимо
    # (ADR-0003, «Обновление 2026-09-24»), и исходная ячейка != sku.
    matched_sku: Mapped[str | None] = mapped_column(String(255), nullable=True)
    product_id: Mapped[int | None] = mapped_column(ForeignKey("products.id"), nullable=True)
    quantity: Mapped[Decimal | None] = mapped_column(Numeric(18, 4), nullable=True)
    dimensions: Mapped[dict | None] = mapped_column(JSONB(none_as_null=True), nullable=True)
    # Признак пройденных операций строки (ADR-0055): по нему остаток, созданный
    # этой строкой, отличается от остатка соседней строки того же артикула,
    # участка и длины. Нужен «посмотреть» в истории: текущий остаток строки
    # ищется по полному ключу баланса.
    completed_operations: Mapped[list | None] = mapped_column(
        JSONB(none_as_null=True), nullable=True
    )
    target_section_id: Mapped[int | None] = mapped_column(
        ForeignKey("sections.id"), nullable=True
    )
    quality_state: Mapped[str | None] = mapped_column(String(20), nullable=True)
    status: Mapped[StockImportRowStatus] = mapped_column(
        String(20), nullable=False
    )
    # Ссылка справочная, а ledger — источник истины: при чистке проводок она
    # обнуляется, а не блокирует удаление. Прецедент — `defects.route_stage_id`
    # с ondelete="SET NULL" (см. NULLABLE_FK_REFS в routes_seed).
    stock_transaction_id: Mapped[int | None] = mapped_column(
        ForeignKey("stock_transactions.id", ondelete="SET NULL"), nullable=True
    )
    errors: Mapped[list] = mapped_column(
        JSONB, nullable=False, server_default=text("'[]'::jsonb"), default=list
    )
    warnings: Mapped[list] = mapped_column(
        JSONB, nullable=False, server_default=text("'[]'::jsonb"), default=list
    )
    raw_values: Mapped[list] = mapped_column(
        JSONB, nullable=False, server_default=text("'[]'::jsonb"), default=list
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
