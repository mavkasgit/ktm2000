"""planning and imports

Revision ID: 004_planning_and_imports
Revises: 003_routes
Create Date: 2026-06-05 15:03:00.000000
"""

from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision: str = '004_planning_and_imports'
down_revision: Union[str, None] = '003_routes'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # 1. Create import_files
    op.create_table('import_files',
        sa.Column('id', sa.BigInteger(), sa.Identity(always=True), nullable=False),
        sa.Column('original_filename', sa.String(length=500), nullable=False),
        sa.Column('stored_path', sa.String(length=1000), nullable=True),
        sa.Column('content_type', sa.String(length=255), nullable=True),
        sa.Column('file_extension', sa.String(length=20), nullable=False),
        sa.Column('detected_format', sa.String(length=50), nullable=False),
        sa.Column('file_sha256', sa.String(length=64), nullable=False),
        sa.Column('size_bytes', sa.BigInteger(), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('file_sha256')
    )

    # 2. Create production_plans
    op.create_table('production_plans',
        sa.Column('id', sa.BigInteger(), sa.Identity(always=True), nullable=False),
        sa.Column('plan_no', sa.String(length=100), nullable=False),
        sa.Column('name', sa.String(length=255), nullable=False),
        sa.Column('status', sa.Enum('draft', 'validated', 'approved', 'partially_released', 'released', 'cancelled', name='production_plan_status'), server_default=sa.text("'draft'"), nullable=False),
        sa.Column('period_start', sa.Date(), nullable=True),
        sa.Column('period_end', sa.Date(), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('plan_no')
    )

    # 3. Create import_batches
    op.create_table('import_batches',
        sa.Column('id', sa.BigInteger(), sa.Identity(always=True), nullable=False),
        sa.Column('source_file_id', sa.BigInteger(), nullable=False),
        sa.Column('production_plan_id', sa.BigInteger(), nullable=False),
        sa.Column('template_id', sa.BigInteger(), nullable=True),
        sa.Column('rule_profile_id', sa.BigInteger(), nullable=True),
        sa.Column('mode', sa.Enum('create_plan', 'append_to_plan', 'replace_draft_from_same_source', name='import_batch_mode'), nullable=False),
        sa.Column('status', sa.Enum('parsed', 'failed', 'applied', 'cancelled', name='import_batch_status'), server_default=sa.text("'parsed'"), nullable=False),
        sa.Column('source_system', sa.String(length=100), server_default=sa.text("'excel'"), nullable=False),
        sa.Column('sheet_name', sa.String(length=255), nullable=False),
        sa.Column('header_row_number', sa.BigInteger(), nullable=False),
        sa.Column('total_rows', sa.BigInteger(), nullable=False),
        sa.Column('parsed_rows', sa.BigInteger(), nullable=False),
        sa.Column('summary', postgresql.JSONB(astext_type=sa.Text()), server_default=sa.text("'{}'::jsonb"), nullable=False),
        sa.Column('rules_snapshot', postgresql.JSONB(astext_type=sa.Text()), server_default=sa.text("'[]'::jsonb"), nullable=False),
        sa.Column('route_selection_diagnostics', postgresql.JSONB(astext_type=sa.Text()), server_default=sa.text("'{}'::jsonb"), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.ForeignKeyConstraint(['production_plan_id'], ['production_plans.id'], ),
        sa.ForeignKeyConstraint(['rule_profile_id'], ['route_rule_profiles.id'], ),
        sa.ForeignKeyConstraint(['source_file_id'], ['import_files.id'], ),
        sa.ForeignKeyConstraint(['template_id'], ['import_templates.id'], ),
        sa.PrimaryKeyConstraint('id')
    )

    # 4. Create plan_positions
    op.create_table('plan_positions',
        sa.Column('id', sa.BigInteger(), sa.Identity(always=True), nullable=False),
        sa.Column('production_plan_id', sa.BigInteger(), nullable=False),
        sa.Column('product_id', sa.BigInteger(), nullable=True),
        sa.Column('source_type', sa.Enum('manual', 'excel_import', 'api', 'integration', name='plan_source_type'), nullable=False),
        sa.Column('source_system', sa.String(length=100), nullable=True),
        sa.Column('source_ref', sa.String(length=255), nullable=True),
        sa.Column('source_fingerprint', sa.String(length=64), nullable=True),
        sa.Column('external_plan_id', sa.String(length=255), nullable=True),
        sa.Column('source_row_hash', sa.String(length=64), nullable=True),
        sa.Column('import_batch_id', sa.BigInteger(), nullable=True),
        sa.Column('source_sku', sa.String(length=255), nullable=False),
        sa.Column('output_sku', sa.String(length=255), server_default=sa.text("''"), nullable=False),
        sa.Column('source_name', sa.String(length=1000), nullable=True),
        sa.Column('quantity', sa.Numeric(precision=14, scale=3), nullable=False),
        sa.Column('source_payload', postgresql.JSONB(astext_type=sa.Text()), server_default=sa.text("'{}'::jsonb"), nullable=False),
        sa.Column('due_date', sa.Date(), nullable=True),
        sa.Column('period_start', sa.Date(), nullable=True),
        sa.Column('period_end', sa.Date(), nullable=True),
        sa.Column('customer', sa.String(length=255), nullable=True),
        sa.Column('priority', sa.BigInteger(), server_default=sa.text('100'), nullable=False),
        sa.Column('source_row_number', sa.BigInteger(), nullable=True),
        sa.Column('route_id', sa.BigInteger(), nullable=True),
        sa.Column('route_profile_id', sa.BigInteger(), nullable=True),
        sa.Column('has_pack_ops', sa.Boolean(), nullable=True),
        sa.Column('route_origin', sa.Enum('auto', 'manual_confirmed', 'legacy', name='plan_position_route_origin'), nullable=True),
        sa.Column('route_match_quality', sa.Enum('exact', 'corrected', 'unknown', name='plan_position_route_match_quality'), nullable=True),
        sa.Column('route_match_reason', sa.Enum('wildcard_rule', 'fallback_first_active', 'selection_rules', 'no_route_candidate', 'route_rule_conflict', 'legacy', name='plan_position_route_match_reason'), nullable=True),
        sa.Column('route_assigned_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('route_manual_confirmed_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('status', sa.Enum('draft', 'invalid', 'valid', 'approved', 'released', 'cancelled', name='plan_position_status'), nullable=False),
        sa.Column('validation_status', sa.Enum('pending', 'valid', 'invalid', name='plan_position_validation_status'), nullable=False),
        sa.Column('validation_errors', postgresql.JSONB(astext_type=sa.Text()), server_default=sa.text("'[]'::jsonb"), nullable=False),
        sa.Column('approved_by', sa.BigInteger(), nullable=True),
        sa.Column('approved_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('released_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('deleted_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('deleted_by', sa.BigInteger(), nullable=True),
        sa.Column('delete_reason', sa.Text(), nullable=True),
        sa.ForeignKeyConstraint(['approved_by'], ['users.id'], ),
        sa.ForeignKeyConstraint(['deleted_by'], ['users.id'], ),
        sa.ForeignKeyConstraint(['import_batch_id'], ['import_batches.id'], ),
        sa.ForeignKeyConstraint(['product_id'], ['products.id'], ),
        sa.ForeignKeyConstraint(['production_plan_id'], ['production_plans.id'], ),
        sa.ForeignKeyConstraint(['route_id'], ['production_routes.id'], ),
        sa.ForeignKeyConstraint(['route_profile_id'], ['route_rule_profiles.id'], ),
        sa.PrimaryKeyConstraint('id')
    )
    op.create_index('ix_plan_positions_import_hash', 'plan_positions', ['import_batch_id', 'source_row_hash'], unique=True)
    op.create_index('ix_plan_positions_import_row', 'plan_positions', ['import_batch_id', 'source_row_number'], unique=True)

    # 5. Create plan_change_sets
    op.create_table('plan_change_sets',
        sa.Column('id', sa.BigInteger(), sa.Identity(always=True), nullable=False),
        sa.Column('production_plan_id', sa.BigInteger(), nullable=False),
        sa.Column('import_batch_id', sa.BigInteger(), nullable=True),
        sa.Column('status', sa.Enum('draft', 'applied', 'cancelled', name='plan_change_set_status'), server_default=sa.text("'draft'"), nullable=False),
        sa.Column('summary', postgresql.JSONB(astext_type=sa.Text()), server_default=sa.text("'{}'::jsonb"), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.ForeignKeyConstraint(['import_batch_id'], ['import_batches.id'], ),
        sa.ForeignKeyConstraint(['production_plan_id'], ['production_plans.id'], ),
        sa.PrimaryKeyConstraint('id')
    )

    # 6. Create plan_change_items
    op.create_table('plan_change_items',
        sa.Column('id', sa.BigInteger(), sa.Identity(always=True), nullable=False),
        sa.Column('change_set_id', sa.BigInteger(), nullable=False),
        sa.Column('plan_position_id', sa.BigInteger(), nullable=True),
        sa.Column('source_row_number', sa.BigInteger(), nullable=True),
        sa.Column('source_ref', sa.String(length=255), nullable=True),
        sa.Column('change_action', sa.Enum('create_position', 'update_draft_position', 'mark_possible_duplicate', 'ignore_unchanged', 'cancel_draft_position', name='plan_change_action'), nullable=False),
        sa.Column('before_data', postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column('after_data', postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column('status', sa.Enum('pending', 'warning', 'invalid', 'applied', name='plan_change_item_status'), nullable=False),
        sa.Column('warnings', postgresql.JSONB(astext_type=sa.Text()), server_default=sa.text("'[]'::jsonb"), nullable=False),
        sa.Column('errors', postgresql.JSONB(astext_type=sa.Text()), server_default=sa.text("'[]'::jsonb"), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.ForeignKeyConstraint(['change_set_id'], ['plan_change_sets.id'], ),
        sa.ForeignKeyConstraint(['plan_position_id'], ['plan_positions.id'], ),
        sa.PrimaryKeyConstraint('id')
    )
    op.create_index('ix_plan_change_items_change_set', 'plan_change_items', ['change_set_id'], unique=False)

    # 7. Create position_status_history
    op.create_table('position_status_history',
        sa.Column('id', sa.BigInteger(), sa.Identity(always=True), nullable=False),
        sa.Column('plan_position_id', sa.BigInteger(), nullable=False),
        sa.Column('from_status', sa.String(length=20), nullable=False),
        sa.Column('to_status', sa.String(length=20), nullable=False),
        sa.Column('changed_by', sa.BigInteger(), nullable=True),
        sa.Column('changed_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.Column('reason', sa.Text(), nullable=True),
        sa.ForeignKeyConstraint(['changed_by'], ['users.id'], ),
        sa.ForeignKeyConstraint(['plan_position_id'], ['plan_positions.id'], ),
        sa.PrimaryKeyConstraint('id')
    )
    op.create_index('ix_history_position', 'position_status_history', ['plan_position_id'], unique=False)
    op.create_index('ix_history_position_status_time', 'position_status_history', ['plan_position_id', 'to_status', 'changed_at'], unique=False)

    # 8. Create release_batches
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
        sa.ForeignKeyConstraint(['created_by'], ['users.id'], ),
        sa.ForeignKeyConstraint(['production_plan_id'], ['production_plans.id'], ),
        sa.ForeignKeyConstraint(['released_by'], ['users.id'], ),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('batch_no')
    )

    # 9. Create release_batch_positions
    op.create_table('release_batch_positions',
        sa.Column('id', sa.BigInteger(), sa.Identity(always=True), nullable=False),
        sa.Column('release_batch_id', sa.BigInteger(), nullable=False),
        sa.Column('plan_position_id', sa.BigInteger(), nullable=False),
        sa.Column('release_quantity', sa.Numeric(precision=14, scale=3), nullable=False),
        sa.Column('route_id', sa.BigInteger(), nullable=False),
        sa.Column('route_snapshot', postgresql.JSONB(astext_type=sa.Text()), server_default=sa.text("'{}'::jsonb"), nullable=False),
        sa.ForeignKeyConstraint(['plan_position_id'], ['plan_positions.id'], ),
        sa.ForeignKeyConstraint(['release_batch_id'], ['release_batches.id'], ),
        sa.ForeignKeyConstraint(['route_id'], ['production_routes.id'], ),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('release_batch_id', 'plan_position_id', name='uq_release_batch_position')
    )


def downgrade() -> None:
    op.drop_table('release_batch_positions')
    op.drop_table('release_batches')
    sa.Enum(name='release_batch_status').drop(op.get_bind(), checkfirst=False)
    sa.Enum(name='release_batch_type').drop(op.get_bind(), checkfirst=False)
    op.drop_index('ix_history_position_status_time', table_name='position_status_history')
    op.drop_index('ix_history_position', table_name='position_status_history')
    op.drop_table('position_status_history')
    op.drop_index('ix_plan_change_items_change_set', table_name='plan_change_items')
    op.drop_table('plan_change_items')
    sa.Enum(name='plan_change_item_status').drop(op.get_bind(), checkfirst=False)
    sa.Enum(name='plan_change_action').drop(op.get_bind(), checkfirst=False)
    op.drop_table('plan_change_sets')
    sa.Enum(name='plan_change_set_status').drop(op.get_bind(), checkfirst=False)
    op.drop_index('ix_plan_positions_import_row', table_name='plan_positions')
    op.drop_index('ix_plan_positions_import_hash', table_name='plan_positions')
    op.drop_table('plan_positions')
    sa.Enum(name='plan_position_status').drop(op.get_bind(), checkfirst=False)
    sa.Enum(name='plan_position_validation_status').drop(op.get_bind(), checkfirst=False)
    sa.Enum(name='plan_position_route_origin').drop(op.get_bind(), checkfirst=False)
    sa.Enum(name='plan_position_route_match_quality').drop(op.get_bind(), checkfirst=False)
    sa.Enum(name='plan_position_route_match_reason').drop(op.get_bind(), checkfirst=False)
    sa.Enum(name='plan_source_type').drop(op.get_bind(), checkfirst=False)
    op.drop_table('import_batches')
    sa.Enum(name='import_batch_status').drop(op.get_bind(), checkfirst=False)
    sa.Enum(name='import_batch_mode').drop(op.get_bind(), checkfirst=False)
    op.drop_table('production_plans')
    sa.Enum(name='production_plan_status').drop(op.get_bind(), checkfirst=False)
    op.drop_table('import_files')
