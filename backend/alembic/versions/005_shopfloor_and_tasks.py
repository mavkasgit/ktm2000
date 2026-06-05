"""shopfloor and tasks

Revision ID: 005_shopfloor_and_tasks
Revises: 004_planning_and_imports
Create Date: 2026-06-05 15:04:00.000000
"""

from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa

revision: str = '005_shopfloor_and_tasks'
down_revision: Union[str, None] = '004_planning_and_imports'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # 1. Create internal_plans
    op.create_table('internal_plans',
        sa.Column('id', sa.BigInteger(), sa.Identity(always=True), nullable=False),
        sa.Column('production_plan_id', sa.BigInteger(), nullable=False),
        sa.Column('release_batch_id', sa.BigInteger(), nullable=True),
        sa.Column('status', sa.Enum('active', 'cancelled', 'completed', name='internal_plan_status'), server_default=sa.text("'active'"), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.ForeignKeyConstraint(['production_plan_id'], ['production_plans.id'], ),
        sa.ForeignKeyConstraint(['release_batch_id'], ['release_batches.id'], ),
        sa.PrimaryKeyConstraint('id')
    )
    op.create_index('ix_internal_plans_release_batch', 'internal_plans', ['release_batch_id'], unique=True)

    # 2. Create section_plan_lines
    op.create_table('section_plan_lines',
        sa.Column('id', sa.BigInteger(), sa.Identity(always=True), nullable=False),
        sa.Column('internal_plan_id', sa.BigInteger(), nullable=False),
        sa.Column('plan_position_id', sa.BigInteger(), nullable=False),
        sa.Column('section_id', sa.BigInteger(), nullable=False),
        sa.Column('product_id', sa.BigInteger(), nullable=False),
        sa.Column('route_id', sa.BigInteger(), nullable=False),
        sa.Column('route_stage_id', sa.BigInteger(), nullable=False),
        sa.Column('sequence', sa.Integer(), nullable=False),
        sa.Column('planned_quantity', sa.Numeric(precision=14, scale=3), nullable=False),
        sa.Column('due_date', sa.Date(), nullable=True),
        sa.Column('cached_available_quantity', sa.Numeric(precision=14, scale=3), server_default=sa.text('0'), nullable=False),
        sa.Column('cached_issued_quantity', sa.Numeric(precision=14, scale=3), server_default=sa.text('0'), nullable=False),
        sa.Column('cached_completed_quantity', sa.Numeric(precision=14, scale=3), server_default=sa.text('0'), nullable=False),
        sa.Column('cached_transferred_quantity', sa.Numeric(precision=14, scale=3), server_default=sa.text('0'), nullable=False),
        sa.Column('cached_received_quantity', sa.Numeric(precision=14, scale=3), server_default=sa.text('0'), nullable=False),
        sa.Column('cached_rejected_quantity', sa.Numeric(precision=14, scale=3), server_default=sa.text('0'), nullable=False),
        sa.Column('cached_remaining_quantity', sa.Numeric(precision=14, scale=3), server_default=sa.text('0'), nullable=False),
        sa.ForeignKeyConstraint(['internal_plan_id'], ['internal_plans.id'], ),
        sa.ForeignKeyConstraint(['plan_position_id'], ['plan_positions.id'], ),
        sa.ForeignKeyConstraint(['product_id'], ['products.id'], ),
        sa.ForeignKeyConstraint(['route_id'], ['production_routes.id'], ),
        sa.ForeignKeyConstraint(['route_stage_id'], ['route_stages.id'], ),
        sa.ForeignKeyConstraint(['section_id'], ['sections.id'], ),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('internal_plan_id', 'plan_position_id', 'route_stage_id', name='uq_section_plan_lines_stage')
    )

    # 3. Create work_tasks
    op.create_table('work_tasks',
        sa.Column('id', sa.BigInteger(), sa.Identity(always=True), nullable=False),
        sa.Column('section_plan_line_id', sa.BigInteger(), nullable=False),
        sa.Column('section_id', sa.BigInteger(), nullable=False),
        sa.Column('product_id', sa.BigInteger(), nullable=False),
        sa.Column('route_stage_id', sa.BigInteger(), nullable=False),
        sa.Column('planned_quantity', sa.Numeric(precision=14, scale=3), nullable=False),
        sa.Column('status', sa.Enum('waiting_previous', 'ready', 'in_progress', 'partially_completed', 'completed', 'cancelled', name='work_task_status'), nullable=False),
        sa.Column('due_date', sa.Date(), nullable=True),
        sa.Column('assigned_to', sa.BigInteger(), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.Column('cached_available_quantity', sa.Numeric(precision=14, scale=3), server_default=sa.text('0'), nullable=False),
        sa.Column('cached_issued_quantity', sa.Numeric(precision=14, scale=3), server_default=sa.text('0'), nullable=False),
        sa.Column('cached_in_work_quantity', sa.Numeric(precision=14, scale=3), server_default=sa.text('0'), nullable=False),
        sa.Column('cached_completed_quantity', sa.Numeric(precision=14, scale=3), server_default=sa.text('0'), nullable=False),
        sa.Column('cached_transferred_quantity', sa.Numeric(precision=14, scale=3), server_default=sa.text('0'), nullable=False),
        sa.Column('cached_received_quantity', sa.Numeric(precision=14, scale=3), server_default=sa.text('0'), nullable=False),
        sa.Column('cached_rejected_quantity', sa.Numeric(precision=14, scale=3), server_default=sa.text('0'), nullable=False),
        sa.Column('cached_remaining_quantity', sa.Numeric(precision=14, scale=3), server_default=sa.text('0'), nullable=False),
        sa.Column('selected_operation_code', sa.String(length=100), nullable=True),
        sa.CheckConstraint('cached_available_quantity >= 0', name='ck_work_tasks_cached_available_quantity_non_negative'),
        sa.CheckConstraint('cached_completed_quantity >= 0', name='ck_work_tasks_cached_completed_quantity_non_negative'),
        sa.CheckConstraint('cached_in_work_quantity >= 0', name='ck_work_tasks_cached_in_work_quantity_non_negative'),
        sa.CheckConstraint('cached_issued_quantity >= 0', name='ck_work_tasks_cached_issued_quantity_non_negative'),
        sa.CheckConstraint('cached_received_quantity >= 0', name='ck_work_tasks_cached_received_quantity_non_negative'),
        sa.CheckConstraint('cached_rejected_quantity >= 0', name='ck_work_tasks_cached_rejected_quantity_non_negative'),
        sa.CheckConstraint('cached_remaining_quantity >= 0', name='ck_work_tasks_cached_remaining_quantity_non_negative'),
        sa.CheckConstraint('cached_transferred_quantity >= 0', name='ck_work_tasks_cached_transferred_quantity_non_negative'),
        sa.CheckConstraint('planned_quantity >= 0', name='ck_work_tasks_planned_quantity_non_negative'),
        sa.ForeignKeyConstraint(['assigned_to'], ['users.id'], ),
        sa.ForeignKeyConstraint(['product_id'], ['products.id'], ),
        sa.ForeignKeyConstraint(['route_stage_id'], ['route_stages.id'], ),
        sa.ForeignKeyConstraint(['section_id'], ['sections.id'], ),
        sa.ForeignKeyConstraint(['section_plan_line_id'], ['section_plan_lines.id'], ),
        sa.PrimaryKeyConstraint('id')
    )


def downgrade() -> None:
    op.drop_table('work_tasks')
    sa.Enum(name='work_task_status').drop(op.get_bind(), checkfirst=False)
    op.drop_table('section_plan_lines')
    op.drop_index('ix_internal_plans_release_batch', table_name='internal_plans')
    op.drop_table('internal_plans')
    sa.Enum(name='internal_plan_status').drop(op.get_bind(), checkfirst=False)
