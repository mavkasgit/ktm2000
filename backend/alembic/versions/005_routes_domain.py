"""routes domain: production_routes, route_steps, route_matching_rules, route_rule_conditions,
route_signature_rules, route_selection_rules, route_rule_profiles, section_operations

Revision ID: 005_routes_domain
Revises: 004_planning_domain
Create Date: 2026-05-25 12:04:00.000000
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision: str = '005_routes_domain'
down_revision: Union[str, None] = '004_planning_domain'
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
    _create_enum_if_not_exists("route_operation_family", ["NONE", "DRILL", "PRESS", "PACK", "SPUNBOND", "STRETCH"])
    _create_enum_if_not_exists("route_output_kind", ["finished_good", "semi_finished_shipment"])
    op.create_table('production_routes',
        sa.Column('id', sa.BigInteger(), sa.Identity(always=True), primary_key=True),
        sa.Column('code', sa.String(100), nullable=True, unique=True),
        sa.Column('name', sa.String(255), nullable=False, unique=True),
        sa.Column('description', sa.Text(), nullable=True),
        sa.Column('is_active', sa.Boolean(), nullable=False, server_default=sa.text("true")),
        sa.Column('sort_order', sa.Integer(), nullable=False, server_default=sa.text("0")),
    )

    # route_steps
    op.create_table('route_steps',
        sa.Column('id', sa.BigInteger(), sa.Identity(always=True), primary_key=True),
        sa.Column('route_id', sa.BigInteger(), sa.ForeignKey('production_routes.id'), nullable=False),
        sa.Column('sequence', sa.Integer(), nullable=False),
        sa.Column('section_id', sa.BigInteger(), sa.ForeignKey('sections.id'), nullable=False),
        sa.Column('operation_code', sa.String(100), nullable=True),
        sa.Column('operation_name', sa.String(255), nullable=False),
        sa.Column('is_significant', sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column('norm_time_minutes', sa.Integer(), nullable=True),
        sa.Column('requires_acceptance', sa.Boolean(), nullable=False, server_default=sa.text("true")),
        sa.Column('allow_parallel', sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column('is_final', sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.UniqueConstraint('route_id', 'sequence', name='uq_route_steps_sequence'),
    )

    # route_matching_rules
    op.create_table('route_matching_rules',
        sa.Column('id', sa.BigInteger(), sa.Identity(always=True), primary_key=True),
        sa.Column('route_id', sa.BigInteger(), sa.ForeignKey('production_routes.id'), nullable=False),
        sa.Column('priority', sa.Integer(), nullable=False, server_default=sa.text("0")),
        sa.Column('created_at', sa.DateTime(), server_default=sa.func.now()),
    )

    # route_rule_conditions
    op.create_table('route_rule_conditions',
        sa.Column('id', sa.BigInteger(), sa.Identity(always=True), primary_key=True),
        sa.Column('rule_id', sa.BigInteger(), sa.ForeignKey('route_matching_rules.id'), nullable=False),
        sa.Column('field', sa.String(100), nullable=False),
        sa.Column('operator', sa.String(10), nullable=False),
        sa.Column('value', sa.Text(), nullable=False),
    )

    # route_signature_rules
    op.create_table('route_signature_rules',
        sa.Column('id', sa.BigInteger(), sa.Identity(always=True), primary_key=True),
        sa.Column('route_id', sa.BigInteger(), sa.ForeignKey('production_routes.id'), nullable=False),
        sa.Column('operation_family', postgresql.ENUM("NONE", "DRILL", "PRESS", "PACK", "SPUNBOND", "STRETCH", name="route_operation_family", create_type=False), nullable=False),
        sa.Column('output_kind', postgresql.ENUM("finished_good", "semi_finished_shipment", name="route_output_kind", create_type=False), nullable=False),
        sa.Column('has_pack_ops', sa.Boolean(), nullable=True),
        sa.Column('priority', sa.Integer(), nullable=False, server_default=sa.text("0")),
        sa.Column('is_active', sa.Boolean(), nullable=False, server_default=sa.text("true")),
        sa.Column('created_at', sa.DateTime(), server_default=sa.text("now()")),
    )
    op.create_index('ix_route_signature_rules_lookup', 'route_signature_rules',
        ['operation_family', 'output_kind', 'has_pack_ops', 'is_active', 'priority'])

    # route_selection_rules
    op.create_table('route_selection_rules',
        sa.Column('id', sa.BigInteger(), sa.Identity(always=True), primary_key=True),
        sa.Column('code', sa.String(100), nullable=True, unique=True),
        sa.Column('name', sa.String(255), nullable=False),
        sa.Column('profile_id', sa.BigInteger(), nullable=True),
        sa.Column('priority', sa.Integer(), nullable=False, server_default=sa.text("0")),
        sa.Column('is_active', sa.Boolean(), nullable=False, server_default=sa.text("true")),
        sa.Column('conditions', postgresql.JSONB(astext_type=sa.Text()), nullable=False, server_default=sa.text("'[]'::jsonb")),
        sa.Column('actions', postgresql.JSONB(astext_type=sa.Text()), nullable=False, server_default=sa.text("'[]'::jsonb")),
        sa.Column('phase', sa.String(20), nullable=False, server_default=sa.text("'route_select'")),
        sa.Column('created_at', sa.DateTime(), server_default=sa.func.now()),
    )
    op.create_index('ix_route_selection_rules_priority', 'route_selection_rules', ['priority', 'id'])
    op.create_index('ix_route_selection_rules_active_profile_phase_priority', 'route_selection_rules',
        ['is_active', 'profile_id', 'phase', 'priority'])

    # route_rule_profiles
    op.create_table('route_rule_profiles',
        sa.Column('id', sa.BigInteger(), sa.Identity(always=True), primary_key=True),
        sa.Column('code', sa.String(100), nullable=False, unique=True),
        sa.Column('name', sa.String(255), nullable=False),
        sa.Column('is_active', sa.Boolean(), nullable=False, server_default=sa.text("true")),
        sa.Column('priority', sa.Integer(), nullable=False, server_default=sa.text("0")),
        sa.Column('import_template_id', sa.BigInteger(), nullable=True),
        sa.Column('excel_column_passport', postgresql.JSONB(astext_type=sa.Text()), nullable=False, server_default=sa.text("'[]'::jsonb")),
        sa.Column('excel_passport_meta', postgresql.JSONB(astext_type=sa.Text()), nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column('created_at', sa.DateTime(), server_default=sa.func.now()),
    )

    # section_operations
    op.create_table('section_operations',
        sa.Column('id', sa.BigInteger(), sa.Identity(always=True), primary_key=True),
        sa.Column('section_id', sa.BigInteger(), sa.ForeignKey('sections.id'), nullable=False),
        sa.Column('operation_code', sa.String(100), nullable=False),
        sa.Column('operation_name', sa.String(255), nullable=False),
        sa.Column('is_significant', sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column('icon', sa.String(50), nullable=True),
        sa.Column('icon_color', sa.String(7), nullable=True),
        sa.UniqueConstraint('section_id', 'operation_code', name='uq_section_operations'),
    )


def downgrade() -> None:
    op.drop_table('section_operations')
    op.drop_table('route_rule_profiles')
    op.drop_index('ix_route_selection_rules_active_profile_phase_priority', table_name='route_selection_rules')
    op.drop_index('ix_route_selection_rules_priority', table_name='route_selection_rules')
    op.drop_table('route_selection_rules')
    op.drop_index('ix_route_signature_rules_lookup', table_name='route_signature_rules')
    op.drop_table('route_signature_rules')
    op.drop_table('route_rule_conditions')
    op.drop_table('route_matching_rules')
    op.drop_table('route_steps')
    op.drop_table('production_routes')

    sa.Enum(name='route_output_kind').drop(op.get_bind(), checkfirst=True)
    sa.Enum(name='route_operation_family').drop(op.get_bind(), checkfirst=True)
