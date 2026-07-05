"""routes

Эпик: Маршруты, этапы, правила подбора
Irreversible: no

Revision ID: 004_routes
Revises: 003_spg_and_balances
Create Date: 2026-07-05 19:00:00.000000
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision: str = "004_routes"
down_revision: Union[str, None] = "003_spg_and_balances"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # --- SCHEMA ---
    op.create_table('import_templates',
    sa.Column('id', sa.BigInteger(), sa.Identity(always=True), nullable=False),
    sa.Column('code', sa.String(length=100), nullable=True),
    sa.Column('name', sa.String(length=255), nullable=False),
    sa.Column('button_label', sa.String(length=100), nullable=True),
    sa.Column('is_active', sa.Boolean(), server_default=sa.text('true'), nullable=False),
    sa.Column('sort_order', sa.Integer(), server_default=sa.text('0'), nullable=False),
    sa.Column('column_mapping', postgresql.JSONB(astext_type=sa.Text()), server_default=sa.text("'{}'::jsonb"), nullable=False),
    sa.Column('description', sa.Text(), nullable=True),
    sa.Column('created_by', sa.BigInteger(), nullable=True),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.ForeignKeyConstraint(['created_by'], ['users.id'], name=op.f('fk_import_templates_created_by_users')),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_import_templates')),
    sa.UniqueConstraint('code', name=op.f('uq_import_templates_code'))
    )
    op.create_table('production_routes',
    sa.Column('id', sa.BigInteger(), sa.Identity(always=True), nullable=False),
    sa.Column('code', sa.String(length=100), nullable=True),
    sa.Column('name', sa.String(length=255), nullable=False),
    sa.Column('description', sa.Text(), nullable=True),
    sa.Column('is_active', sa.Boolean(), server_default=sa.text('true'), nullable=False),
    sa.Column('sort_order', sa.Integer(), server_default=sa.text('0'), nullable=False),
    sa.Column('import_template_id', sa.BigInteger(), nullable=True),
    sa.ForeignKeyConstraint(['import_template_id'], ['import_templates.id'], name=op.f('fk_production_routes_import_template_id_import_templates')),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_production_routes')),
    sa.UniqueConstraint('code', name=op.f('uq_production_routes_code')),
    sa.UniqueConstraint('name', name=op.f('uq_production_routes_name'))
    )
    op.create_table('route_rule_profiles',
    sa.Column('id', sa.BigInteger(), sa.Identity(always=True), nullable=False),
    sa.Column('code', sa.String(length=100), nullable=False),
    sa.Column('name', sa.String(length=255), nullable=False),
    sa.Column('is_active', sa.Boolean(), server_default=sa.text('true'), nullable=False),
    sa.Column('priority', sa.Integer(), server_default=sa.text('0'), nullable=False),
    sa.Column('route_sections', postgresql.JSONB(astext_type=sa.Text()), server_default=sa.text("'[]'::jsonb"), nullable=False),
    sa.Column('route_name_pattern', sa.String(length=255), server_default=sa.text("'{output_kind} - {operations}'"), nullable=False),
    sa.Column('import_template_id', sa.BigInteger(), nullable=True),
    sa.Column('excel_column_passport', postgresql.JSONB(astext_type=sa.Text()), server_default=sa.text("'[]'::jsonb"), nullable=False),
    sa.Column('excel_passport_meta', postgresql.JSONB(astext_type=sa.Text()), server_default=sa.text("'{}'::jsonb"), nullable=False),
    sa.Column('created_at', sa.DateTime(), server_default=sa.text('now()'), nullable=False),
    sa.ForeignKeyConstraint(['import_template_id'], ['import_templates.id'], name=op.f('fk_route_rule_profiles_import_template_id_import_templates')),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_route_rule_profiles')),
    sa.UniqueConstraint('code', name=op.f('uq_route_rule_profiles_code'))
    )
    op.create_table('route_selection_rules',
    sa.Column('id', sa.BigInteger(), sa.Identity(always=True), nullable=False),
    sa.Column('code', sa.String(length=100), nullable=True),
    sa.Column('name', sa.String(length=255), nullable=False),
    sa.Column('profile_id', sa.BigInteger(), nullable=True),
    sa.Column('priority', sa.Integer(), server_default=sa.text('0'), nullable=False),
    sa.Column('is_active', sa.Boolean(), server_default=sa.text('true'), nullable=False),
    sa.Column('conditions', postgresql.JSONB(astext_type=sa.Text()), server_default=sa.text("'[]'::jsonb"), nullable=False),
    sa.Column('actions', postgresql.JSONB(astext_type=sa.Text()), server_default=sa.text("'[]'::jsonb"), nullable=False),
    sa.Column('phase', sa.String(length=20), server_default=sa.text("'route_select'"), nullable=False),
    sa.Column('created_at', sa.DateTime(), server_default=sa.text('now()'), nullable=False),
    sa.ForeignKeyConstraint(['profile_id'], ['route_rule_profiles.id'], name=op.f('fk_route_selection_rules_profile_id_route_rule_profiles')),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_route_selection_rules')),
    sa.UniqueConstraint('code', name=op.f('uq_route_selection_rules_code'))
    )
    op.create_table('route_matching_rules',
    sa.Column('id', sa.BigInteger(), sa.Identity(always=True), nullable=False),
    sa.Column('route_id', sa.BigInteger(), nullable=False),
    sa.Column('priority', sa.Integer(), server_default=sa.text('0'), nullable=False),
    sa.Column('created_at', sa.DateTime(), server_default=sa.text('now()'), nullable=False),
    sa.ForeignKeyConstraint(['route_id'], ['production_routes.id'], name=op.f('fk_route_matching_rules_route_id_production_routes')),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_route_matching_rules'))
    )
    op.create_table('route_stages',
    sa.Column('id', sa.BigInteger(), sa.Identity(always=True), nullable=False),
    sa.Column('route_id', sa.BigInteger(), nullable=False),
    sa.Column('sequence', sa.Integer(), nullable=False),
    sa.Column('section_id', sa.BigInteger(), nullable=True),
    sa.Column('is_significant', sa.Boolean(), server_default=sa.text('false'), nullable=False),
    sa.Column('norm_time_minutes', sa.Integer(), nullable=True),
    sa.Column('requires_acceptance', sa.Boolean(), server_default=sa.text('true'), nullable=False),
    sa.Column('allow_parallel', sa.Boolean(), server_default=sa.text('false'), nullable=False),
    sa.Column('is_final', sa.Boolean(), server_default=sa.text('false'), nullable=False),
    sa.Column('sort_order', sa.Integer(), server_default=sa.text('0'), nullable=False),
    sa.Column('stage_kind', sa.Enum('production', 'transit', name='route_stage_kind'), server_default=sa.text("'production'"), nullable=False),
    sa.Column('storage_section_id', sa.BigInteger(), nullable=True),
    sa.ForeignKeyConstraint(['route_id'], ['production_routes.id'], name=op.f('fk_route_stages_route_id_production_routes')),
    sa.ForeignKeyConstraint(['section_id'], ['sections.id'], name=op.f('fk_route_stages_section_id_sections')),
    sa.ForeignKeyConstraint(['storage_section_id'], ['sections.id'], name=op.f('fk_route_stages_storage_section_id_sections')),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_route_stages')),
    sa.UniqueConstraint('route_id', 'sequence', name='uq_route_stages_sequence')
    )
    op.create_table('route_operations',
    sa.Column('id', sa.BigInteger(), sa.Identity(always=True), nullable=False),
    sa.Column('route_stage_id', sa.BigInteger(), nullable=False),
    sa.Column('sequence', sa.Integer(), server_default=sa.text('1'), nullable=False),
    sa.Column('operation_code', sa.String(length=100), nullable=True),
    sa.Column('operation_name', sa.String(length=255), nullable=False),
    sa.ForeignKeyConstraint(['route_stage_id'], ['route_stages.id'], name=op.f('fk_route_operations_route_stage_id_route_stages')),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_route_operations')),
    sa.UniqueConstraint('route_stage_id', 'sequence', name='uq_route_operations_sequence')
    )
    op.create_table('route_rule_conditions',
    sa.Column('id', sa.BigInteger(), sa.Identity(always=True), nullable=False),
    sa.Column('rule_id', sa.BigInteger(), nullable=False),
    sa.Column('field', sa.String(length=100), nullable=False),
    sa.Column('operator', sa.String(length=10), nullable=False),
    sa.Column('value', sa.Text(), nullable=False),
    sa.ForeignKeyConstraint(['rule_id'], ['route_matching_rules.id'], name=op.f('fk_route_rule_conditions_rule_id_route_matching_rules')),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_route_rule_conditions'))
    )

    # --- DATA ---
    pass

    # --- TRIGGERS ---
    pass


def downgrade() -> None:
    op.drop_table('route_rule_conditions')
    op.drop_table('route_operations')
    op.drop_table('route_stages')
    op.drop_table('route_matching_rules')
    op.drop_table('route_selection_rules')
    op.drop_table('route_rule_profiles')
    op.drop_table('production_routes')
    op.drop_table('import_templates')
