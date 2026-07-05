"""release_and_shopfloor

Эпик: Выпуск в цех, внутренние планы, задания
Irreversible: no

Revision ID: 006_release_and_shopfloor
Revises: 005_planning_and_imports
Create Date: 2026-07-05 19:00:00.000000
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision: str = "006_release_and_shopfloor"
down_revision: Union[str, None] = "005_planning_and_imports"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # --- SCHEMA ---
    op.create_table('release_batches',
    sa.Column('id', sa.BigInteger(), sa.Identity(always=True), nullable=False),
    sa.Column('batch_no', sa.String(length=100), nullable=False),
    sa.Column('production_plan_id', sa.BigInteger(), nullable=False),
    sa.Column('name', sa.String(length=255), nullable=False),
    sa.Column('batch_type', sa.Enum('near_term', 'weekly', 'future_preparation', 'manual', name='release_batch_type'), nullable=False),
    sa.Column('status', sa.Enum('draft', 'released', 'cancelled', name='release_batch_status'), server_default=sa.text("'draft'"), nullable=False),
    sa.Column('horizon_start', sa.Date(), nullable=True),
    sa.Column('horizon_end', sa.Date(), nullable=True),
    sa.Column('created_by', sa.BigInteger(), nullable=True),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('released_by', sa.BigInteger(), nullable=True),
    sa.Column('released_at', sa.DateTime(timezone=True), nullable=True),
    sa.ForeignKeyConstraint(['created_by'], ['users.id'], name=op.f('fk_release_batches_created_by_users')),
    sa.ForeignKeyConstraint(['production_plan_id'], ['production_plans.id'], name=op.f('fk_release_batches_production_plan_id_production_plans')),
    sa.ForeignKeyConstraint(['released_by'], ['users.id'], name=op.f('fk_release_batches_released_by_users')),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_release_batches')),
    sa.UniqueConstraint('batch_no', name=op.f('uq_release_batches_batch_no'))
    )
    op.create_table('release_batch_positions',
    sa.Column('id', sa.BigInteger(), sa.Identity(always=True), nullable=False),
    sa.Column('release_batch_id', sa.BigInteger(), nullable=False),
    sa.Column('plan_position_id', sa.BigInteger(), nullable=False),
    sa.Column('release_quantity', sa.Numeric(precision=14, scale=3), nullable=False),
    sa.Column('route_id', sa.BigInteger(), nullable=False),
    sa.Column('route_snapshot', postgresql.JSONB(astext_type=sa.Text()), server_default=sa.text("'{}'::jsonb"), nullable=False),
    sa.ForeignKeyConstraint(['plan_position_id'], ['plan_positions.id'], name=op.f('fk_release_batch_positions_plan_position_id_plan_positions')),
    sa.ForeignKeyConstraint(['release_batch_id'], ['release_batches.id'], name=op.f('fk_release_batch_positions_release_batch_id_release_batches')),
    sa.ForeignKeyConstraint(['route_id'], ['production_routes.id'], name=op.f('fk_release_batch_positions_route_id_production_routes')),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_release_batch_positions')),
    sa.UniqueConstraint('release_batch_id', 'plan_position_id', name='uq_release_batch_position')
    )
    op.create_table('internal_plans',
    sa.Column('id', sa.BigInteger(), sa.Identity(always=True), nullable=False),
    sa.Column('production_plan_id', sa.BigInteger(), nullable=False),
    sa.Column('release_batch_id', sa.BigInteger(), nullable=True),
    sa.Column('status', sa.Enum('active', 'cancelled', 'completed', name='internal_plan_status'), server_default=sa.text("'active'"), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.ForeignKeyConstraint(['production_plan_id'], ['production_plans.id'], name=op.f('fk_internal_plans_production_plan_id_production_plans')),
    sa.ForeignKeyConstraint(['release_batch_id'], ['release_batches.id'], name=op.f('fk_internal_plans_release_batch_id_release_batches')),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_internal_plans'))
    )
    op.create_index('ix_internal_plans_release_batch', 'internal_plans', ['release_batch_id'], unique=True)
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
    sa.ForeignKeyConstraint(['internal_plan_id'], ['internal_plans.id'], name=op.f('fk_section_plan_lines_internal_plan_id_internal_plans')),
    sa.ForeignKeyConstraint(['plan_position_id'], ['plan_positions.id'], name=op.f('fk_section_plan_lines_plan_position_id_plan_positions')),
    sa.ForeignKeyConstraint(['product_id'], ['products.id'], name=op.f('fk_section_plan_lines_product_id_products')),
    sa.ForeignKeyConstraint(['route_id'], ['production_routes.id'], name=op.f('fk_section_plan_lines_route_id_production_routes')),
    sa.ForeignKeyConstraint(['route_stage_id'], ['route_stages.id'], name=op.f('fk_section_plan_lines_route_stage_id_route_stages')),
    sa.ForeignKeyConstraint(['section_id'], ['sections.id'], name=op.f('fk_section_plan_lines_section_id_sections')),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_section_plan_lines')),
    sa.UniqueConstraint('internal_plan_id', 'plan_position_id', 'route_stage_id', name='uq_section_plan_lines_stage')
    )
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
    sa.Column('selected_operation_code', sa.String(length=100), nullable=True),
    sa.CheckConstraint('planned_quantity >= 0', name=op.f('ck_work_tasks_planned_quantity_non_negative')),
    sa.ForeignKeyConstraint(['assigned_to'], ['users.id'], name=op.f('fk_work_tasks_assigned_to_users')),
    sa.ForeignKeyConstraint(['product_id'], ['products.id'], name=op.f('fk_work_tasks_product_id_products')),
    sa.ForeignKeyConstraint(['route_stage_id'], ['route_stages.id'], name=op.f('fk_work_tasks_route_stage_id_route_stages')),
    sa.ForeignKeyConstraint(['section_id'], ['sections.id'], name=op.f('fk_work_tasks_section_id_sections')),
    sa.ForeignKeyConstraint(['section_plan_line_id'], ['section_plan_lines.id'], name=op.f('fk_work_tasks_section_plan_line_id_section_plan_lines')),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_work_tasks'))
    )

    # --- DATA ---
    pass

    # --- TRIGGERS ---
    pass


def downgrade() -> None:
    op.drop_table('work_tasks')
    op.drop_table('section_plan_lines')
    op.drop_table('internal_plans')
    op.drop_table('release_batch_positions')
    op.drop_table('release_batches')
