"""Коды номенклатуры 1С и поля источника в строках импорта (#455).

Фундамент режима «Остатки из 1С» (спека ``docs/stock-import-1c-spec.md`` §4):

1. ``product_1c_codes`` — отдельный справочник кодов номенклатуры 1С.
   Код не заменяет ``Product.code`` (ADR-0012): у одного артикула бывает
   несколько кодов 1С (``20933``, ``22069``, ``10926``), поэтому связь
   «многие коды → один артикул». ``code`` уникален глобально: один код 1С
   не может указывать на два артикула. Удаление артикула уносит его коды
   (``ON DELETE CASCADE``) — справочник производный от артикула.

2. ``stock_import_rows.source_code`` / ``source_quantity_m`` — исходный код
   номенклатуры и метры из «Конечное сальдо / Количество». ``quantity``
   остаётся штуками; у строк обычного шаблона оба поля NULL.

3. ``stock_import_rows.product_id`` → ``ON DELETE SET NULL``: строка импорта —
   история (ADR-0052), а не ссылочная целостность. До изменения удаление
   артикула, встречавшегося в применённом импорте, падало на FK, хотя строка
   и без продукта остаётся осмысленной (``sku``, ``source_code``, проводка
   обнуляется отдельно — прецедент 073). Импортные строки не должны мешать
   удалению артикула.

``downgrade`` возвращает FK ``product_id`` к прежнему поведению и убирает
колонки с таблицей. Строки истории с ``product_id IS NULL`` остаются
валидными — колонка nullable, данные не теряются.

Повторный прогон безопасен (конвенция 052: ``stamp`` назад + ``upgrade head``):
таблица, индекс и колонки создаются с ``IF NOT EXISTS``; замена FK —
drop + create по имени, которое существует после 072.
"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "086_product_1c_codes_source_fields"
down_revision: str | None = "085_section_operation_updated_at"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

PRODUCT_FK = "fk_stock_import_rows_product_id_products"


def upgrade() -> None:
    # --- SCHEMA ---
    op.create_table(
        "product_1c_codes",
        sa.Column("id", sa.BigInteger(), sa.Identity(always=True), nullable=False),
        sa.Column("product_id", sa.BigInteger(), nullable=False),
        sa.Column("code", sa.String(length=64), nullable=False),
        sa.Column(
            "source",
            sa.String(length=32),
            server_default=sa.text("'1c_osv'"),
            nullable=False,
        ),
        sa.Column("created_by", sa.BigInteger(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["created_by"],
            ["users.id"],
            name=op.f("fk_product_1c_codes_created_by_users"),
        ),
        sa.ForeignKeyConstraint(
            ["product_id"],
            ["products.id"],
            name=op.f("fk_product_1c_codes_product_id_products"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_product_1c_codes")),
        sa.UniqueConstraint("code", name="uq_product_1c_codes_code"),
        if_not_exists=True,
    )
    op.create_index(
        op.f("ix_product_1c_codes_product_id"),
        "product_1c_codes",
        ["product_id"],
        unique=False,
        if_not_exists=True,
    )
    op.add_column(
        "stock_import_rows",
        sa.Column("source_code", sa.String(length=64), nullable=True),
        if_not_exists=True,
    )
    op.add_column(
        "stock_import_rows",
        sa.Column("source_quantity_m", sa.Numeric(precision=18, scale=4), nullable=True),
        if_not_exists=True,
    )
    op.drop_constraint(PRODUCT_FK, "stock_import_rows", type_="foreignkey")
    op.create_foreign_key(
        PRODUCT_FK,
        "stock_import_rows",
        "products",
        ["product_id"],
        ["id"],
        ondelete="SET NULL",
    )

    # --- DATA ---

    # --- TRIGGERS ---


def downgrade() -> None:
    # Строки истории с product_id IS NULL переживут откат: колонка nullable.
    op.drop_constraint(PRODUCT_FK, "stock_import_rows", type_="foreignkey")
    op.create_foreign_key(
        PRODUCT_FK,
        "stock_import_rows",
        "products",
        ["product_id"],
        ["id"],
    )
    op.drop_column("stock_import_rows", "source_quantity_m", if_exists=True)
    op.drop_column("stock_import_rows", "source_code", if_exists=True)
    op.drop_index(
        op.f("ix_product_1c_codes_product_id"),
        table_name="product_1c_codes",
        if_exists=True,
    )
    op.drop_table("product_1c_codes", if_exists=True)
