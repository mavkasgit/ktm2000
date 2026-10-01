"""История импорта остатков — реестр батчей и строк (ADR-0052, ADR-0053).

Импорт остатков сегодня оставлял единственный след — узел ``action_journal``
с ``action_type='import_remainders'`` и общий ``source_ref`` на проводках.
Имя файла, лист, per-row вердикты и ошибки не сохранялись, а ``action_id`` не
отдавался в ответе ``POST /stock/import/remainders``, поэтому батч было нечем
опознать ни в UI, ни в ссылке.

Схема:

* ``stock_import_batches`` — заголовок батча. Отдельная таблица, а не
  переиспользование ``import_batches``: там ``production_plan_id``, ``mode``,
  ``sheet_name``, ``header_row_number`` — ``NOT NULL`` и все про план
  (ADR-0052 п.1). ``import_files`` переиспользуется как есть.
* ``stock_import_rows`` — строка импорта (ADR-0052 п.8): вердикт, ошибки,
  сырые значения файла и обязательная ссылка на созданную ею проводку
  ``stock_transaction_id``.

Бэкфилл (ADR-0052 п.7): строки для всех существующих
``Action(action_type='import_remainders')``. Порядок применения известен
точно — ``Action.id`` монотонен, — в отличие от ADR-0025, где бэкфилл
``applied_at`` был отвергнут из-за невосстановимого порядка. У legacy-строк
нет файла и per-row данных: ``file_id IS NULL``, ``legacy = true``.

Повторный прогон безопасен (конвенция 052: тесты ревизий делают ``stamp``
назад и ``upgrade head`` гоняет хвост цепочки поверх уже поднятой схемы):
обе таблицы и индексы создаются с ``IF NOT EXISTS``, бэкфилл защищён
``NOT EXISTS`` по ``action_id``.
"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "072_stock_import_history"
down_revision: str | None = "071_route_code_identity"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

REMAINDER_ACTION_TYPE = "import_remainders"

# ``status`` батча: applied → rolled_back. Значения ``parsed``/``failed``
# планового ``import_batch_status`` невозможны — импорт остатков однофазный
# (ADR-0052 п.2). Скрытие из списка — не статус, а ``deleted_at`` (п.5):
# скрытый батч может быть и откатанным, и нет.
BATCH_STATUS = ("applied", "rolled_back")

ROW_STATUS = ("valid", "invalid")


def upgrade() -> None:
    op.create_table(
        "stock_import_batches",
        sa.Column("id", sa.BigInteger(), sa.Identity(always=True), nullable=False),
        sa.Column("action_id", sa.BigInteger(), nullable=False),
        sa.Column("file_id", sa.BigInteger(), nullable=True),
        sa.Column("status", sa.String(length=20), nullable=False, server_default="applied"),
        sa.Column(
            "legacy",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("false"),
        ),
        sa.Column(
            "clear_existing",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("false"),
        ),
        # NULL только у legacy-батчей (ADR-0052 п.7): проводки импорта несут
        # и приход в секцию, и гашение из неё, а узел журнала склад не
        # помнит. Приписать им склад первого батча — значило бы соврать, а
        # фиктивный id нарушил бы FK на sections.
        sa.Column("location_id", sa.BigInteger(), nullable=True),
        sa.Column("sheet_name", sa.String(length=255), nullable=True),
        sa.Column("total_rows", sa.BigInteger(), nullable=False, server_default="0"),
        sa.Column("imported_rows", sa.BigInteger(), nullable=False, server_default="0"),
        sa.Column("skipped_rows", sa.BigInteger(), nullable=False, server_default="0"),
        sa.Column("summary", postgresql.JSONB(astext_type=sa.Text()), nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column("created_by", sa.Integer(), nullable=True),
        sa.Column("created_by_name", sa.String(length=255), nullable=True),
        sa.Column("rolled_back_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("rolled_back_by", sa.Integer(), nullable=True),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("deleted_by", sa.Integer(), nullable=True),
        sa.Column("delete_reason", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.CheckConstraint(
            "status IN ('applied', 'rolled_back')",
            name="ck_stock_import_batches_status",
        ),
        sa.ForeignKeyConstraint(
            ["action_id"], ["action_journal.id"], name="fk_stock_import_batches_action_id_action_journal"
        ),
        sa.ForeignKeyConstraint(
            ["file_id"], ["import_files.id"], name="fk_stock_import_batches_file_id_import_files"
        ),
        sa.ForeignKeyConstraint(
            ["location_id"], ["sections.id"], name="fk_stock_import_batches_location_id_sections"
        ),
        sa.ForeignKeyConstraint(["created_by"], ["users.id"], name="fk_stock_import_batches_created_by_users"),
        sa.ForeignKeyConstraint(["deleted_by"], ["users.id"], name="fk_stock_import_batches_deleted_by_users"),
        sa.ForeignKeyConstraint(
            ["rolled_back_by"], ["users.id"], name="fk_stock_import_batches_rolled_back_by_users"
        ),
        sa.PrimaryKeyConstraint("id", name="pk_stock_import_batches"),
        sa.UniqueConstraint("action_id", name="uq_stock_import_batches_action_id"),
        # Конвенция 052: таблица могла остаться от прошлого прогона.
        if_not_exists=True,
    )
    op.create_index("ix_stock_import_batches_location_id", "stock_import_batches", ["location_id"], if_not_exists=True)
    op.create_index("ix_stock_import_batches_status", "stock_import_batches", ["status"], if_not_exists=True)
    op.create_index("ix_stock_import_batches_created_at", "stock_import_batches", ["created_at"], if_not_exists=True)

    op.create_table(
        "stock_import_rows",
        sa.Column("id", sa.BigInteger(), sa.Identity(always=True), nullable=False),
        sa.Column("batch_id", sa.BigInteger(), nullable=False),
        sa.Column("source_row_number", sa.Integer(), nullable=False),
        sa.Column("sku", sa.String(length=255), nullable=False, server_default=""),
        sa.Column("matched_sku", sa.String(length=255), nullable=True),
        sa.Column("product_id", sa.BigInteger(), nullable=True),
        sa.Column("quantity", sa.Numeric(precision=18, scale=4), nullable=True),
        sa.Column("dimensions", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("target_section_id", sa.BigInteger(), nullable=True),
        sa.Column("quality_state", sa.String(length=20), nullable=True),
        sa.Column("status", sa.String(length=20), nullable=False),
        sa.Column("stock_transaction_id", sa.BigInteger(), nullable=True),
        sa.Column("errors", postgresql.JSONB(astext_type=sa.Text()), nullable=False, server_default=sa.text("'[]'::jsonb")),
        sa.Column("warnings", postgresql.JSONB(astext_type=sa.Text()), nullable=False, server_default=sa.text("'[]'::jsonb")),
        # Сырые значения строки файла — источник истины в споре «в файле было
        # так, а залили так» (ADR-0052 п.8).
        sa.Column("raw_values", postgresql.JSONB(astext_type=sa.Text()), nullable=False, server_default=sa.text("'[]'::jsonb")),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.CheckConstraint("status IN ('valid', 'invalid')", name="ck_stock_import_rows_status"),
        sa.ForeignKeyConstraint(
            ["batch_id"], ["stock_import_batches.id"], name="fk_stock_import_rows_batch_id_stock_import_batches"
        ),
        sa.ForeignKeyConstraint(["product_id"], ["products.id"], name="fk_stock_import_rows_product_id_products"),
        sa.ForeignKeyConstraint(
            ["target_section_id"], ["sections.id"], name="fk_stock_import_rows_target_section_id_sections"
        ),
        sa.ForeignKeyConstraint(
            ["stock_transaction_id"],
            ["stock_transactions.id"],
            name="fk_stock_import_rows_stock_transaction_id_stock_transactions",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_stock_import_rows"),
        if_not_exists=True,
    )
    op.create_index("ix_stock_import_rows_batch_id", "stock_import_rows", ["batch_id"], if_not_exists=True)

    # Бэкфилл истории (ADR-0052 п.7). ``location_id`` у legacy-импортов
    # неизвестен, поэтому NULL: склад не сохранился, и UI это помечает.
    # LIFO по складу (ADR-0053) legacy-батчи не касается — область
    # отката у них неизвестна, они откатываются как есть по узлу журнала.
    op.execute(
        sa.text(
            """
            INSERT INTO stock_import_batches
                (action_id, file_id, location_id, status, legacy, clear_existing,
                 total_rows, imported_rows, skipped_rows, summary,
                 created_by_name, created_at)
            SELECT
                a.id,
                NULL,
                NULL,
                CASE WHEN a.status = 'active' THEN 'applied' ELSE 'rolled_back' END,
                true,
                false,
                (SELECT count(*) FROM stock_transactions t WHERE t.action_id = a.id),
                (SELECT count(*) FROM stock_transactions t
                  WHERE t.action_id = a.id AND t.reason = 'manual_in'),
                0,
                '{}'::jsonb,
                a.actor,
                a.created_at
            FROM action_journal a
            WHERE a.action_type = :action_type
              AND NOT EXISTS (
                  SELECT 1 FROM stock_import_batches b WHERE b.action_id = a.id
              )
            """
        ).bindparams(action_type=REMAINDER_ACTION_TYPE)
    )


def downgrade() -> None:
    op.drop_index("ix_stock_import_rows_batch_id", table_name="stock_import_rows")
    op.drop_table("stock_import_rows")
    op.drop_index("ix_stock_import_batches_created_at", table_name="stock_import_batches")
    op.drop_index("ix_stock_import_batches_status", table_name="stock_import_batches")
    op.drop_index("ix_stock_import_batches_location_id", table_name="stock_import_batches")
    op.drop_table("stock_import_batches")
