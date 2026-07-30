"""dimension_types reference + product_dimensions bindings (ADR-0001, п. 3)

Revision ID: 022_dimension_types
Revises: 021_backchannel_logout_slo
Create Date: 2026-07-30

"""

from alembic import op
import sqlalchemy as sa

revision = "022_dimension_types"
down_revision = "021_backchannel_logout_slo"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "dimension_types",
        sa.Column("id", sa.BigInteger(), sa.Identity(always=True), primary_key=True, autoincrement=True),
        sa.Column("code", sa.String(length=100), nullable=False),
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.Column("unit", sa.String(length=50), nullable=False),
        sa.Column("value_type", sa.String(length=50), server_default=sa.text("'number'"), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.UniqueConstraint("code", name="uq_dimension_types_code"),
    )
    op.create_index("ix_dimension_types_code", "dimension_types", ["code"])

    op.create_table(
        "product_dimensions",
        sa.Column("id", sa.BigInteger(), sa.Identity(always=True), primary_key=True, autoincrement=True),
        sa.Column(
            "product_id",
            sa.BigInteger(),
            sa.ForeignKey("products.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "dimension_type_id",
            sa.BigInteger(),
            sa.ForeignKey("dimension_types.id"),
            nullable=False,
        ),
        sa.Column("is_required", sa.Boolean(), server_default=sa.text("false"), nullable=False),
        sa.Column("default_value", sa.Float(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.UniqueConstraint("product_id", "dimension_type_id", name="uq_product_dimensions_product_type"),
    )
    op.create_index("ix_product_dimensions_product_id", "product_dimensions", ["product_id"])


def downgrade() -> None:
    op.drop_index("ix_product_dimensions_product_id", table_name="product_dimensions")
    op.drop_table("product_dimensions")
    op.drop_index("ix_dimension_types_code", table_name="dimension_types")
    op.drop_table("dimension_types")
