"""add product lengths, processing flags and is_laminated

Revision ID: 005_product_lengths_flags
Revises: d9e0f1a2b3c4
Create Date: 2026-05-10 16:00:00.000000

"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = '005_product_lengths_flags'
down_revision: Union[str, None] = 'd9e0f1a2b3c4'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


PROCESSING_FLAGS = [
    ("WINDOW", "Оконный профиль", "PRESS"),
    ("COMB", "Комбинированный профиль", "PRESS"),
    ("DRILL", "Сверловка", None),
    ("GLUE", "Склейка", None),
    ("DIFFUSER", "Диффузор", None),
    ("RUBBER", "Резинка", None),
    ("RUBBER_DRILL", "Сверловка резинки", None),
    ("SHOT_SKIP", "Пропуск дробеструйки", None),
]


def upgrade() -> None:
    # 1. Add is_laminated to products
    op.add_column(
        "products",
        sa.Column("is_laminated", sa.Boolean(), server_default=sa.text("false"), nullable=False),
    )

    # 2. Create product_lengths
    op.create_table(
        "product_lengths",
        sa.Column("id", sa.BigInteger(), sa.Identity(always=True), primary_key=True),
        sa.Column("product_id", sa.BigInteger(), sa.ForeignKey("products.id"), nullable=False),
        sa.Column("length_mm", sa.Float(), nullable=False),
        sa.CheckConstraint("length_mm > 0", name="ck_product_lengths_positive"),
        sa.UniqueConstraint("product_id", "length_mm", name="uq_product_lengths_product_length"),
    )
    op.create_index("ix_product_lengths_product_id", "product_lengths", ["product_id"])

    # 3. Create processing_flags
    op.create_table(
        "processing_flags",
        sa.Column("id", sa.BigInteger(), sa.Identity(always=True), primary_key=True),
        sa.Column("code", sa.String(50), nullable=False, unique=True),
        sa.Column("name", sa.String(200), nullable=False),
        sa.Column("section_scope", sa.String(50), nullable=True),
        sa.Column("is_active", sa.Boolean(), server_default=sa.text("true"), nullable=False),
    )

    # Seed processing flags
    flags_table = sa.table(
        "processing_flags",
        sa.column("code", sa.String),
        sa.column("name", sa.String),
        sa.column("section_scope", sa.String),
        sa.column("is_active", sa.Boolean),
    )
    op.bulk_insert(
        flags_table,
        [
            {"code": code, "name": name, "section_scope": scope, "is_active": True}
            for code, name, scope in PROCESSING_FLAGS
        ],
    )

    # 4. Create product_processing_flags
    op.create_table(
        "product_processing_flags",
        sa.Column("product_id", sa.BigInteger(), sa.ForeignKey("products.id"), nullable=False),
        sa.Column("flag_id", sa.BigInteger(), sa.ForeignKey("processing_flags.id"), nullable=False),
        sa.UniqueConstraint("product_id", "flag_id", name="uq_product_flags_product_flag"),
    )
    op.create_index("ix_product_processing_flags_product_id", "product_processing_flags", ["product_id"])

    # 5. Backfill: link skip_shot_blast=true products to SHOT_SKIP flag
    # Get SHOT_SKIP flag id
    conn = op.get_bind()
    result = conn.execute(
        sa.text("SELECT id FROM processing_flags WHERE code = 'SHOT_SKIP'")
    )
    shot_skip_id = result.scalar()

    if shot_skip_id:
        # Insert links for products with skip_shot_blast = true
        conn.execute(
            sa.text("""
                INSERT INTO product_processing_flags (product_id, flag_id)
                SELECT id, :flag_id FROM products
                WHERE skip_shot_blast = true
                AND id NOT IN (SELECT product_id FROM product_processing_flags WHERE flag_id = :flag_id)
            """),
            {"flag_id": shot_skip_id},
        )


def downgrade() -> None:
    op.drop_index("ix_product_processing_flags_product_id", table_name="product_processing_flags")
    op.drop_table("product_processing_flags")
    op.drop_index("ix_product_lengths_product_id", table_name="product_lengths")
    op.drop_table("product_lengths")
    op.drop_column("products", "is_laminated")
    # processing_flags table is dropped (seed data goes with it)
    op.drop_table("processing_flags")
