"""Реестр исключений разбора ОСВ 1С (#464).

`product_1c_skipped` — решение человека «эта строка 1С не наша»: химия,
плёнки, крепёж, СИЗ, газы (``not_mes``), покупные рейки и панели
(``purchased``), новые артикулы, которые не заводим (``no_catalog``).
Повторный предпросмотр перестаёт показывать такие строки ошибками — они
уходят в отдельный статус ``skipped`` со своим счётчиком.

Границы:

* связи с ``products`` нет — запись как раз про отсутствие артикула (или про
  чужой домен), а каталог обязан выигрывать у реестра: мэтч идёт по коду и
  имени артикула, реестр читается только для не найденных строк;
* ``code`` уникален, если задан (``UNIQUE`` в PostgreSQL пропускает несколько
  ``NULL``); ``name_norm`` уникален всегда и хранится в той же нормализации,
  что ``_norm_cell`` импорта (lower, NBSP → пробел, схлопывание пробелов);
* хотя бы одно из двух полей заполнено — иначе запись ничего не исключает.

Повторный прогон безопасен (конвенция 052: ``stamp`` назад + ``upgrade head``):
таблица создаётся с ``IF NOT EXISTS``.
"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "088_product_1c_skipped"
down_revision: str | None = "087_product_drawing_slot"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # --- SCHEMA ---
    op.create_table(
        "product_1c_skipped",
        sa.Column("id", sa.BigInteger(), sa.Identity(always=True), nullable=False),
        sa.Column("code", sa.String(length=64), nullable=True),
        sa.Column("name_norm", sa.String(length=500), nullable=True),
        sa.Column("reason", sa.String(length=16), nullable=False),
        sa.Column("note", sa.String(length=500), nullable=True),
        sa.Column(
            "decided_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("decided_by", sa.String(length=100), nullable=True),
        sa.CheckConstraint(
            "code IS NOT NULL OR name_norm IS NOT NULL",
            name="ck_product_1c_skipped_identity",
        ),
        sa.CheckConstraint(
            "reason IN ('not_mes', 'purchased', 'no_catalog')",
            name="ck_product_1c_skipped_reason",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_product_1c_skipped")),
        sa.UniqueConstraint("code", name="uq_product_1c_skipped_code"),
        sa.UniqueConstraint("name_norm", name="uq_product_1c_skipped_name_norm"),
        if_not_exists=True,
    )

    # --- DATA ---

    # --- TRIGGERS ---


def downgrade() -> None:
    op.drop_table("product_1c_skipped", if_exists=True)
