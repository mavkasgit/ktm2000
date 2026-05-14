"""add route sort_order

Revision ID: 008_add_route_sort_order
Revises: d9e0f1a2b3c4
Create Date: 2026-05-14 16:33:14

"""
from alembic import op
import sqlalchemy as sa


revision = "008_add_route_sort_order"
down_revision = "007_position_history_soft_delete"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "production_routes",
        sa.Column("sort_order", sa.Integer(), nullable=False, server_default=sa.text("0")),
    )
    # Set sequential order based on existing name order
    op.execute("""
        WITH numbered AS (
            SELECT id, ROW_NUMBER() OVER (ORDER BY name) - 1 AS rn
            FROM production_routes
        )
        UPDATE production_routes SET sort_order = (SELECT rn * 10 FROM numbered WHERE numbered.id = production_routes.id)
    """)


def downgrade() -> None:
    op.drop_column("production_routes", "sort_order")
