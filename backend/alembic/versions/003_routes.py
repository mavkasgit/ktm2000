"""routes

Revision ID: 003_routes
Revises: 002_products_and_techcards
Create Date: 2026-06-05 15:02:00.000000
"""

from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision: str = '003_routes'
down_revision: Union[str, None] = '002_products_and_techcards'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # 1. Create import_templates
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
        sa.ForeignKeyConstraint(['created_by'], ['users.id'], ),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('code')
    )

    # 2. Create production_routes
    op.create_table('production_routes',
        sa.Column('id', sa.BigInteger(), sa.Identity(always=True), nullable=False),
        sa.Column('code', sa.String(length=100), nullable=True),
        sa.Column('name', sa.String(length=255), nullable=False),
        sa.Column('description', sa.Text(), nullable=True),
        sa.Column('is_active', sa.Boolean(), server_default=sa.text('true'), nullable=False),
        sa.Column('sort_order', sa.Integer(), server_default=sa.text('0'), nullable=False),
        sa.Column('import_template_id', sa.BigInteger(), nullable=True),
        sa.ForeignKeyConstraint(['import_template_id'], ['import_templates.id'], ),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('code'),
        sa.UniqueConstraint('name')
    )

    # 3. Create route_rule_profiles
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
        sa.ForeignKeyConstraint(['import_template_id'], ['import_templates.id'], ),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('code')
    )

    # 4. Create route_matching_rules
    op.create_table('route_matching_rules',
        sa.Column('id', sa.BigInteger(), sa.Identity(always=True), nullable=False),
        sa.Column('route_id', sa.BigInteger(), nullable=False),
        sa.Column('priority', sa.Integer(), server_default=sa.text('0'), nullable=False),
        sa.Column('created_at', sa.DateTime(), server_default=sa.text('now()'), nullable=False),
        sa.ForeignKeyConstraint(['route_id'], ['production_routes.id'], ),
        sa.PrimaryKeyConstraint('id')
    )

    # 5. Create route_selection_rules
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
        sa.ForeignKeyConstraint(['profile_id'], ['route_rule_profiles.id'], ),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('code')
    )

    # 6. Create route_stages
    op.create_table('route_stages',
        sa.Column('id', sa.BigInteger(), sa.Identity(always=True), nullable=False),
        sa.Column('route_id', sa.BigInteger(), nullable=False),
        sa.Column('sequence', sa.Integer(), nullable=False),
        sa.Column('section_id', sa.BigInteger(), nullable=False),
        sa.Column('is_significant', sa.Boolean(), server_default=sa.text('false'), nullable=False),
        sa.Column('norm_time_minutes', sa.Integer(), nullable=True),
        sa.Column('requires_acceptance', sa.Boolean(), server_default=sa.text('true'), nullable=False),
        sa.Column('allow_parallel', sa.Boolean(), server_default=sa.text('false'), nullable=False),
        sa.Column('is_final', sa.Boolean(), server_default=sa.text('false'), nullable=False),
        sa.Column('sort_order', sa.Integer(), server_default=sa.text('0'), nullable=False),
        sa.ForeignKeyConstraint(['route_id'], ['production_routes.id'], ),
        sa.ForeignKeyConstraint(['section_id'], ['sections.id'], ),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('route_id', 'sequence', name='uq_route_stages_sequence')
    )

    # 7. Create route_operations
    op.create_table('route_operations',
        sa.Column('id', sa.BigInteger(), sa.Identity(always=True), nullable=False),
        sa.Column('route_stage_id', sa.BigInteger(), nullable=False),
        sa.Column('sequence', sa.Integer(), server_default=sa.text('1'), nullable=False),
        sa.Column('operation_code', sa.String(length=100), nullable=True),
        sa.Column('operation_name', sa.String(length=255), nullable=False),
        sa.ForeignKeyConstraint(['route_stage_id'], ['route_stages.id'], ),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('route_stage_id', 'sequence', name='uq_route_operations_sequence')
    )

    # 8. Create route_rule_conditions
    op.create_table('route_rule_conditions',
        sa.Column('id', sa.BigInteger(), sa.Identity(always=True), nullable=False),
        sa.Column('rule_id', sa.BigInteger(), nullable=False),
        sa.Column('field', sa.String(length=100), nullable=False),
        sa.Column('operator', sa.String(length=10), nullable=False),
        sa.Column('value', sa.Text(), nullable=False),
        sa.ForeignKeyConstraint(['rule_id'], ['route_matching_rules.id'], ),
        sa.PrimaryKeyConstraint('id')
    )


def downgrade() -> None:
    op.drop_table('route_rule_conditions')
    op.drop_table('route_operations')
    op.drop_table('route_stages')
    op.drop_table('route_selection_rules')
    op.drop_table('route_matching_rules')
    op.drop_table('route_rule_profiles')
    op.drop_table('production_routes')
    op.drop_table('import_templates')
