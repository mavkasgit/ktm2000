"""planning domain: production_plans, plan_positions, plan_change_sets, plan_change_items,
position_status_history, release_batches, release_batch_positions, internal_plans,
section_plan_lines, work_tasks

Revision ID: 004_planning_domain
Revises: 003_sections_users_domain
Create Date: 2026-05-25 12:03:00.000000
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision: str = '004_planning_domain'
down_revision: Union[str, None] = '003_sections_users_domain'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _create_enum_if_not_exists(name: str, values: list[str]) -> None:
    """Create a PostgreSQL enum only if it doesn't already exist."""
    conn = op.get_bind()
    exists = conn.execute(
        sa.text("SELECT EXISTS (SELECT 1 FROM pg_type WHERE typname = :name)").bindparams(name=name)
    ).scalar()
    if not exists:
        postgresql.ENUM(*values, name=name).create(conn)


def upgrade() -> None:
    # ENUMs — created with IF NOT EXISTS to handle cross-migration dependencies
    _create_enum_if_not_exists("production_plan_status", ["draft", "validated", "approved", "partially_released", "released", "cancelled"])
    _create_enum_if_not_exists("plan_source_type", ["manual", "excel_import", "api", "integration"])
    _create_enum_if_not_exists("plan_position_status", ["draft", "invalid", "valid", "approved", "released", "cancelled"])
    _create_enum_if_not_exists("plan_position_validation_status", ["pending", "valid", "invalid"])
    _create_enum_if_not_exists("plan_position_route_origin", ["auto", "manual_confirmed", "legacy"])
    _create_enum_if_not_exists("plan_position_route_match_quality", ["exact", "corrected", "unknown"])
    _create_enum_if_not_exists("plan_position_route_match_reason", ["wildcard_rule", "fallback_first_active", "selection_rules", "no_route_candidate", "route_rule_conflict", "legacy"])
    _create_enum_if_not_exists("plan_change_set_status", ["draft", "applied", "cancelled"])
    _create_enum_if_not_exists("plan_change_action", ["create_position", "update_draft_position", "mark_possible_duplicate", "ignore_unchanged", "cancel_draft_position"])
    _create_enum_if_not_exists("plan_change_item_status", ["pending", "warning", "invalid", "applied"])
    _create_enum_if_not_exists("release_batch_type", ["near_term", "weekly", "future_preparation", "manual"])
    _create_enum_if_not_exists("release_batch_status", ["draft", "released", "cancelled"])
    _create_enum_if_not_exists("internal_plan_status", ["active", "cancelled", "completed"])
    _create_enum_if_not_exists("work_task_status", ["waiting_previous", "ready", "in_progress", "partially_completed", "completed", "cancelled"])
    # Cross-migration enums from 005_routes_domain
    _create_enum_if_not_exists("route_operation_family", ["NONE", "DRILL", "PRESS", "PACK", "SPUNBOND", "STRETCH"])
    _create_enum_if_not_exists("route_output_kind", ["finished_good", "semi_finished_shipment"])
    # production_plans
    op.create_table('production_plans',
        sa.Column('id', sa.BigInteger(), sa.Identity(always=True), primary_key=True),
        sa.Column('plan_no', sa.String(100), nullable=False, unique=True),
        sa.Column('name', sa.String(255), nullable=False),
        sa.Column('status', postgresql.ENUM("draft", "validated", "approved", "partially_released", "released", "cancelled", name="production_plan_status", create_type=False), nullable=False, server_default=sa.text("'draft'")),
        sa.Column('period_start', sa.Date(), nullable=True),
        sa.Column('period_end', sa.Date(), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
    )

    # plan_positions
    op.create_table('plan_positions',
        sa.Column('id', sa.BigInteger(), sa.Identity(always=True), primary_key=True),
        sa.Column('production_plan_id', sa.BigInteger(), sa.ForeignKey('production_plans.id'), nullable=False),
        sa.Column('product_id', sa.BigInteger(), sa.ForeignKey('products.id'), nullable=True),
        sa.Column('source_type', postgresql.ENUM("manual", "excel_import", "api", "integration", name="plan_source_type", create_type=False), nullable=False),
        sa.Column('source_system', sa.String(100), nullable=True),
        sa.Column('source_ref', sa.String(255), nullable=True),
        sa.Column('source_fingerprint', sa.String(64), nullable=True),
        sa.Column('external_plan_id', sa.String(255), nullable=True),
        sa.Column('source_row_hash', sa.String(64), nullable=True),
        sa.Column('import_batch_id', sa.BigInteger(), nullable=True),
        sa.Column('source_sku', sa.String(255), nullable=False),
        sa.Column('output_sku', sa.String(255), nullable=False, server_default=sa.text("''")),
        sa.Column('source_name', sa.String(1000), nullable=True),
        sa.Column('quantity', sa.Numeric(14, 3), nullable=False),
        sa.Column('source_payload', postgresql.JSONB(astext_type=sa.Text()), nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column('due_date', sa.Date(), nullable=True),
        sa.Column('period_start', sa.Date(), nullable=True),
        sa.Column('period_end', sa.Date(), nullable=True),
        sa.Column('customer', sa.String(255), nullable=True),
        sa.Column('priority', sa.BigInteger(), nullable=False, server_default=sa.text("100")),
        sa.Column('source_row_number', sa.BigInteger(), nullable=True),
        sa.Column('route_id', sa.BigInteger(), nullable=True),
        sa.Column('operation_family', postgresql.ENUM("NONE", "DRILL", "PRESS", "PACK", "SPUNBOND", "STRETCH", name="route_operation_family", create_type=False), nullable=True),
        sa.Column('output_kind', postgresql.ENUM("finished_good", "semi_finished_shipment", name="route_output_kind", create_type=False), nullable=True),
        sa.Column('has_pack_ops', sa.Boolean(), nullable=True),
        sa.Column('route_origin', postgresql.ENUM("auto", "manual_confirmed", "legacy", name="plan_position_route_origin", create_type=False), nullable=True),
        sa.Column('route_match_quality', postgresql.ENUM("exact", "corrected", "unknown", name="plan_position_route_match_quality", create_type=False), nullable=True),
        sa.Column('route_match_reason', postgresql.ENUM("wildcard_rule", "fallback_first_active", "selection_rules", "no_route_candidate", "route_rule_conflict", "legacy", name="plan_position_route_match_reason", create_type=False), nullable=True),
        sa.Column('route_assigned_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('route_manual_confirmed_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('status', postgresql.ENUM("draft", "invalid", "valid", "approved", "released", "cancelled", name="plan_position_status", create_type=False), nullable=False),
        sa.Column('validation_status', postgresql.ENUM("pending", "valid", "invalid", name="plan_position_validation_status", create_type=False), nullable=False),
        sa.Column('validation_errors', postgresql.JSONB(astext_type=sa.Text()), nullable=False, server_default=sa.text("'[]'::jsonb")),
        sa.Column('approved_by', sa.BigInteger(), sa.ForeignKey('users.id'), nullable=True),
        sa.Column('approved_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('released_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('deleted_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('deleted_by', sa.BigInteger(), sa.ForeignKey('users.id'), nullable=True),
        sa.Column('delete_reason', sa.Text(), nullable=True),
    )
    op.create_index('ix_plan_positions_import_row', 'plan_positions', ['import_batch_id', 'source_row_number'], unique=True)
    op.create_index('ix_plan_positions_import_hash', 'plan_positions', ['import_batch_id', 'source_row_hash'], unique=True)

    # plan_change_sets
    op.create_table('plan_change_sets',
        sa.Column('id', sa.BigInteger(), sa.Identity(always=True), primary_key=True),
        sa.Column('production_plan_id', sa.BigInteger(), sa.ForeignKey('production_plans.id'), nullable=False),
        sa.Column('import_batch_id', sa.BigInteger(), nullable=True),
        sa.Column('status', postgresql.ENUM("draft", "applied", "cancelled", name="plan_change_set_status", create_type=False), nullable=False, server_default=sa.text("'draft'")),
        sa.Column('summary', postgresql.JSONB(astext_type=sa.Text()), nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
    )

    # plan_change_items
    op.create_table('plan_change_items',
        sa.Column('id', sa.BigInteger(), sa.Identity(always=True), primary_key=True),
        sa.Column('change_set_id', sa.BigInteger(), sa.ForeignKey('plan_change_sets.id'), nullable=False),
        sa.Column('plan_position_id', sa.BigInteger(), sa.ForeignKey('plan_positions.id'), nullable=True),
        sa.Column('source_row_number', sa.BigInteger(), nullable=True),
        sa.Column('source_ref', sa.String(255), nullable=True),
        sa.Column('change_action', postgresql.ENUM("create_position", "update_draft_position", "mark_possible_duplicate", "ignore_unchanged", "cancel_draft_position", name="plan_change_action", create_type=False), nullable=False),
        sa.Column('before_data', postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column('after_data', postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column('status', postgresql.ENUM("pending", "warning", "invalid", "applied", name="plan_change_item_status", create_type=False), nullable=False),
        sa.Column('warnings', postgresql.JSONB(astext_type=sa.Text()), nullable=False, server_default=sa.text("'[]'::jsonb")),
        sa.Column('errors', postgresql.JSONB(astext_type=sa.Text()), nullable=False, server_default=sa.text("'[]'::jsonb")),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
    )
    op.create_index('ix_plan_change_items_change_set', 'plan_change_items', ['change_set_id'])

    # position_status_history
    op.create_table('position_status_history',
        sa.Column('id', sa.BigInteger(), sa.Identity(always=True), primary_key=True),
        sa.Column('plan_position_id', sa.BigInteger(), sa.ForeignKey('plan_positions.id'), nullable=False),
        sa.Column('from_status', sa.String(20), nullable=False),
        sa.Column('to_status', sa.String(20), nullable=False),
        sa.Column('changed_by', sa.BigInteger(), sa.ForeignKey('users.id'), nullable=True),
        sa.Column('changed_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column('reason', sa.Text(), nullable=True),
    )
    op.create_index('ix_history_position', 'position_status_history', ['plan_position_id'])
    op.create_index('ix_history_position_status_time', 'position_status_history', ['plan_position_id', 'to_status', 'changed_at'])

    # release_batches
    op.create_table('release_batches',
        sa.Column('id', sa.BigInteger(), sa.Identity(always=True), primary_key=True),
        sa.Column('batch_no', sa.String(100), nullable=False, unique=True),
        sa.Column('production_plan_id', sa.BigInteger(), sa.ForeignKey('production_plans.id'), nullable=False),
        sa.Column('name', sa.String(255), nullable=False),
        sa.Column('batch_type', postgresql.ENUM("near_term", "weekly", "future_preparation", "manual", name="release_batch_type", create_type=False), nullable=False),
        sa.Column('status', postgresql.ENUM("draft", "released", "cancelled", name="release_batch_status", create_type=False), nullable=False, server_default=sa.text("'draft'")),
        sa.Column('horizon_start', sa.Date(), nullable=True),
        sa.Column('horizon_end', sa.Date(), nullable=True),
        sa.Column('created_by', sa.BigInteger(), sa.ForeignKey('users.id'), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column('released_by', sa.BigInteger(), sa.ForeignKey('users.id'), nullable=True),
        sa.Column('released_at', sa.DateTime(timezone=True), nullable=True),
    )

    # release_batch_positions
    op.create_table('release_batch_positions',
        sa.Column('id', sa.BigInteger(), sa.Identity(always=True), primary_key=True),
        sa.Column('release_batch_id', sa.BigInteger(), sa.ForeignKey('release_batches.id'), nullable=False),
        sa.Column('plan_position_id', sa.BigInteger(), sa.ForeignKey('plan_positions.id'), nullable=False),
        sa.Column('release_quantity', sa.Numeric(14, 3), nullable=False),
        sa.Column('route_id', sa.BigInteger(), nullable=False),
        sa.Column('route_snapshot', postgresql.JSONB(astext_type=sa.Text()), nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.UniqueConstraint('release_batch_id', 'plan_position_id', name='uq_release_batch_position'),
    )

    # internal_plans
    op.create_table('internal_plans',
        sa.Column('id', sa.BigInteger(), sa.Identity(always=True), primary_key=True),
        sa.Column('production_plan_id', sa.BigInteger(), sa.ForeignKey('production_plans.id'), nullable=False),
        sa.Column('release_batch_id', sa.BigInteger(), sa.ForeignKey('release_batches.id'), nullable=True),
        sa.Column('status', postgresql.ENUM("active", "cancelled", "completed", name="internal_plan_status", create_type=False), nullable=False, server_default=sa.text("'active'")),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
    )
    op.create_index('ix_internal_plans_release_batch', 'internal_plans', ['release_batch_id'], unique=True)

    # section_plan_lines
    op.create_table('section_plan_lines',
        sa.Column('id', sa.BigInteger(), sa.Identity(always=True), primary_key=True),
        sa.Column('internal_plan_id', sa.BigInteger(), sa.ForeignKey('internal_plans.id'), nullable=False),
        sa.Column('plan_position_id', sa.BigInteger(), sa.ForeignKey('plan_positions.id'), nullable=False),
        sa.Column('section_id', sa.BigInteger(), sa.ForeignKey('sections.id'), nullable=False),
        sa.Column('product_id', sa.BigInteger(), sa.ForeignKey('products.id'), nullable=False),
        sa.Column('route_id', sa.BigInteger(), nullable=False),
        sa.Column('route_step_id', sa.BigInteger(), nullable=False),
        sa.Column('sequence', sa.Integer(), nullable=False),
        sa.Column('planned_quantity', sa.Numeric(14, 3), nullable=False),
        sa.Column('due_date', sa.Date(), nullable=True),
        sa.Column('cached_available_quantity', sa.Numeric(14, 3), nullable=False, server_default=sa.text("0")),
        sa.Column('cached_issued_quantity', sa.Numeric(14, 3), nullable=False, server_default=sa.text("0")),
        sa.Column('cached_completed_quantity', sa.Numeric(14, 3), nullable=False, server_default=sa.text("0")),
        sa.Column('cached_transferred_quantity', sa.Numeric(14, 3), nullable=False, server_default=sa.text("0")),
        sa.Column('cached_received_quantity', sa.Numeric(14, 3), nullable=False, server_default=sa.text("0")),
        sa.Column('cached_rejected_quantity', sa.Numeric(14, 3), nullable=False, server_default=sa.text("0")),
        sa.Column('cached_remaining_quantity', sa.Numeric(14, 3), nullable=False, server_default=sa.text("0")),
        sa.UniqueConstraint('internal_plan_id', 'plan_position_id', 'route_step_id', name='uq_section_plan_lines_step'),
    )

    # work_tasks
    op.create_table('work_tasks',
        sa.Column('id', sa.BigInteger(), sa.Identity(always=True), primary_key=True),
        sa.Column('section_plan_line_id', sa.BigInteger(), sa.ForeignKey('section_plan_lines.id'), nullable=False),
        sa.Column('section_id', sa.BigInteger(), sa.ForeignKey('sections.id'), nullable=False),
        sa.Column('product_id', sa.BigInteger(), sa.ForeignKey('products.id'), nullable=False),
        sa.Column('route_step_id', sa.BigInteger(), nullable=False),
        sa.Column('planned_quantity', sa.Numeric(14, 3), nullable=False),
        sa.Column('status', postgresql.ENUM("waiting_previous", "ready", "in_progress", "partially_completed", "completed", "cancelled", name="work_task_status", create_type=False), nullable=False),
        sa.Column('due_date', sa.Date(), nullable=True),
        sa.Column('assigned_to', sa.BigInteger(), sa.ForeignKey('users.id'), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column('cached_available_quantity', sa.Numeric(14, 3), nullable=False, server_default=sa.text("0")),
        sa.Column('cached_issued_quantity', sa.Numeric(14, 3), nullable=False, server_default=sa.text("0")),
        sa.Column('cached_in_work_quantity', sa.Numeric(14, 3), nullable=False, server_default=sa.text("0")),
        sa.Column('cached_completed_quantity', sa.Numeric(14, 3), nullable=False, server_default=sa.text("0")),
        sa.Column('cached_transferred_quantity', sa.Numeric(14, 3), nullable=False, server_default=sa.text("0")),
        sa.Column('cached_received_quantity', sa.Numeric(14, 3), nullable=False, server_default=sa.text("0")),
        sa.Column('cached_rejected_quantity', sa.Numeric(14, 3), nullable=False, server_default=sa.text("0")),
        sa.Column('cached_remaining_quantity', sa.Numeric(14, 3), nullable=False, server_default=sa.text("0")),
        sa.Column('selected_operation_code', sa.String(100), nullable=True),
        sa.CheckConstraint('cached_available_quantity >= 0', name='ck_work_tasks_cached_available_quantity_non_negative'),
        sa.CheckConstraint('cached_issued_quantity >= 0', name='ck_work_tasks_cached_issued_quantity_non_negative'),
        sa.CheckConstraint('cached_in_work_quantity >= 0', name='ck_work_tasks_cached_in_work_quantity_non_negative'),
        sa.CheckConstraint('cached_completed_quantity >= 0', name='ck_work_tasks_cached_completed_quantity_non_negative'),
        sa.CheckConstraint('cached_transferred_quantity >= 0', name='ck_work_tasks_cached_transferred_quantity_non_negative'),
        sa.CheckConstraint('cached_received_quantity >= 0', name='ck_work_tasks_cached_received_quantity_non_negative'),
        sa.CheckConstraint('cached_rejected_quantity >= 0', name='ck_work_tasks_cached_rejected_quantity_non_negative'),
        sa.CheckConstraint('cached_remaining_quantity >= 0', name='ck_work_tasks_cached_remaining_quantity_non_negative'),
        sa.CheckConstraint('planned_quantity > 0', name='ck_work_tasks_planned_quantity_positive'),
    )


def downgrade() -> None:
    op.drop_table('work_tasks')
    op.drop_table('section_plan_lines')
    op.drop_index('ix_internal_plans_release_batch', table_name='internal_plans')
    op.drop_table('internal_plans')
    op.drop_table('release_batch_positions')
    op.drop_table('release_batches')
    op.drop_index('ix_history_position_status_time', table_name='position_status_history')
    op.drop_index('ix_history_position', table_name='position_status_history')
    op.drop_table('position_status_history')
    op.drop_index('ix_plan_change_items_change_set', table_name='plan_change_items')
    op.drop_table('plan_change_items')
    op.drop_table('plan_change_sets')
    op.drop_index('ix_plan_positions_import_hash', table_name='plan_positions')
    op.drop_index('ix_plan_positions_import_row', table_name='plan_positions')
    op.drop_table('plan_positions')
    op.drop_table('production_plans')

    # Drop ENUMs
    sa.Enum(name='work_task_status').drop(op.get_bind(), checkfirst=True)
    sa.Enum(name='internal_plan_status').drop(op.get_bind(), checkfirst=True)
    sa.Enum(name='release_batch_status').drop(op.get_bind(), checkfirst=True)
    sa.Enum(name='release_batch_type').drop(op.get_bind(), checkfirst=True)
    sa.Enum(name='plan_change_item_status').drop(op.get_bind(), checkfirst=True)
    sa.Enum(name='plan_change_action').drop(op.get_bind(), checkfirst=True)
    sa.Enum(name='plan_change_set_status').drop(op.get_bind(), checkfirst=True)
    sa.Enum(name='plan_position_route_match_reason').drop(op.get_bind(), checkfirst=True)
    sa.Enum(name='plan_position_route_match_quality').drop(op.get_bind(), checkfirst=True)
    sa.Enum(name='plan_position_route_origin').drop(op.get_bind(), checkfirst=True)
    sa.Enum(name='plan_position_validation_status').drop(op.get_bind(), checkfirst=True)
    sa.Enum(name='plan_position_status').drop(op.get_bind(), checkfirst=True)
    sa.Enum(name='plan_source_type').drop(op.get_bind(), checkfirst=True)
    sa.Enum(name='production_plan_status').drop(op.get_bind(), checkfirst=True)
