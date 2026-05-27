"""warehouse remainders: add return_to_stock movement type and warehouse_remainders table

Revision ID: 010_warehouse_remainders
Revises: 007_shopfloor_domain
Create Date: 2026-05-27 12:00:00.000000
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision: str = '010_warehouse_remainders'
down_revision: Union[str, None] = '009_seed_data'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Add return_to_stock to movement_type enum
    op.execute("ALTER TYPE movement_type ADD VALUE IF NOT EXISTS 'return_to_stock'")

    # Create warehouse_remainders table
    op.create_table(
        'warehouse_remainders',
        sa.Column('id', sa.BigInteger(), sa.Identity(always=True), primary_key=True),
        sa.Column('product_id', sa.BigInteger(), sa.ForeignKey('products.id'), nullable=False),
        sa.Column('section_id', sa.BigInteger(), sa.ForeignKey('sections.id'), nullable=False),
        sa.Column('route_step_id', sa.BigInteger(), sa.ForeignKey('route_steps.id'), nullable=False),
        sa.Column('section_plan_line_id', sa.BigInteger(), sa.ForeignKey('section_plan_lines.id'), nullable=False),
        sa.Column('origin_task_id', sa.BigInteger(), sa.ForeignKey('work_tasks.id'), nullable=False),
        sa.Column('remainder_quantity', sa.Numeric(14, 3), nullable=False, server_default=sa.text("0")),
        sa.Column('original_issued', sa.Numeric(14, 3), nullable=False),
        sa.Column('completed_stages_json', postgresql.JSONB(astext_type=sa.Text()), nullable=False, server_default=sa.text("'[]'::jsonb")),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column('consumed_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('consumed_by_task_id', sa.BigInteger(), sa.ForeignKey('work_tasks.id'), nullable=True),
        sa.CheckConstraint('remainder_quantity >= 0', name='ck_warehouse_remainders_quantity_non_negative'),
    )
    op.create_index('ix_warehouse_remainders_section', 'warehouse_remainders', ['section_id'])
    op.create_index('ix_warehouse_remainders_product', 'warehouse_remainders', ['product_id'])
    op.create_index('ix_warehouse_remainders_active', 'warehouse_remainders',
                    ['section_id', 'product_id'],
                    postgresql_where=sa.text('remainder_quantity > 0 AND consumed_at IS NULL'))


def downgrade() -> None:
    op.drop_index('ix_warehouse_remainders_active', table_name='warehouse_remainders')
    op.drop_index('ix_warehouse_remainders_product', table_name='warehouse_remainders')
    op.drop_index('ix_warehouse_remainders_section', table_name='warehouse_remainders')
    op.drop_table('warehouse_remainders')
    # Note: cannot remove enum value in PostgreSQL, would need to recreate enum
