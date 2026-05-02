"""products boms routes

Revision ID: 0002_products_boms_routes
Revises: 0001_users_sections
Create Date: 2026-05-02
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "0002_products_boms_routes"
down_revision: Union[str, None] = "0001_users_sections"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

product_type = sa.Enum("finished_good", "semi_finished", "component", "material", name="product_type")


def upgrade() -> None:
    op.create_table(
        "products",
        sa.Column("id", sa.BigInteger(), sa.Identity(always=True), primary_key=True),
        sa.Column("sku", sa.String(length=100), nullable=False),
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.Column("type", product_type, nullable=False),
        sa.Column("unit", sa.String(length=50), nullable=False),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.text("true")),
        sa.Column("notes", sa.String(length=1000), nullable=True),
        sa.UniqueConstraint("sku", name="uq_products_sku"),
    )

    op.create_table(
        "boms",
        sa.Column("id", sa.BigInteger(), sa.Identity(always=True), primary_key=True),
        sa.Column("product_id", sa.BigInteger(), sa.ForeignKey("products.id"), nullable=False),
        sa.Column("version", sa.String(length=100), nullable=False),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.text("true")),
    )
    op.create_index("ix_boms_active_one_per_product", "boms", ["product_id"], unique=True, postgresql_where=sa.text("is_active = true"))

    op.create_table(
        "bom_lines",
        sa.Column("id", sa.BigInteger(), sa.Identity(always=True), primary_key=True),
        sa.Column("bom_id", sa.BigInteger(), sa.ForeignKey("boms.id"), nullable=False),
        sa.Column("component_product_id", sa.BigInteger(), sa.ForeignKey("products.id"), nullable=False),
        sa.Column("quantity", sa.Numeric(14, 3), nullable=False),
        sa.Column("unit", sa.String(length=50), nullable=False),
        sa.UniqueConstraint("bom_id", "component_product_id", name="uq_bom_lines_component"),
        sa.CheckConstraint("quantity > 0", name="ck_bom_lines_quantity_gt_zero"),
    )

    op.create_table(
        "production_routes",
        sa.Column("id", sa.BigInteger(), sa.Identity(always=True), primary_key=True),
        sa.Column("product_id", sa.BigInteger(), sa.ForeignKey("products.id"), nullable=False),
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.Column("version", sa.String(length=100), nullable=False),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.text("true")),
    )
    op.create_index(
        "ix_routes_active_one_per_product",
        "production_routes",
        ["product_id"],
        unique=True,
        postgresql_where=sa.text("is_active = true"),
    )

    op.create_table(
        "route_steps",
        sa.Column("id", sa.BigInteger(), sa.Identity(always=True), primary_key=True),
        sa.Column("route_id", sa.BigInteger(), sa.ForeignKey("production_routes.id"), nullable=False),
        sa.Column("sequence", sa.Integer(), nullable=False),
        sa.Column("section_id", sa.BigInteger(), sa.ForeignKey("sections.id"), nullable=False),
        sa.Column("operation_name", sa.String(length=255), nullable=False),
        sa.Column("norm_time_minutes", sa.Integer(), nullable=True),
        sa.Column("requires_acceptance", sa.Boolean(), nullable=False, server_default=sa.text("true")),
        sa.Column("allow_parallel", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column("is_final", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.UniqueConstraint("route_id", "sequence", name="uq_route_steps_sequence"),
        sa.CheckConstraint("sequence > 0", name="ck_route_steps_sequence_gt_zero"),
    )


def downgrade() -> None:
    op.drop_table("route_steps")
    op.drop_index("ix_routes_active_one_per_product", table_name="production_routes")
    op.drop_table("production_routes")
    op.drop_table("bom_lines")
    op.drop_index("ix_boms_active_one_per_product", table_name="boms")
    op.drop_table("boms")
    op.drop_table("products")
    product_type.drop(op.get_bind(), checkfirst=True)
