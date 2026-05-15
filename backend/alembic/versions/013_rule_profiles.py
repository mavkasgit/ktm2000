"""flexible_routes_rule_profiles

Revision ID: 013_rule_profiles
Revises: 012_seed_system_user
Create Date: 2026-05-15 03:00:00.000000
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB


# revision identifiers, used by Alembic.
revision: str = '013_rule_profiles'
down_revision: Union[str, None] = '012_seed_system_user'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # 1. Add code to production_routes
    op.add_column('production_routes', sa.Column('code', sa.String(100), nullable=True))
    op.create_unique_constraint('uq_production_routes_code', 'production_routes', ['code'])

    # 2. Create route_rule_profiles table
    op.create_table(
        'route_rule_profiles',
        sa.Column('id', sa.BigInteger, sa.Identity(always=True), primary_key=True),
        sa.Column('code', sa.String(100), nullable=False, unique=True),
        sa.Column('name', sa.String(255), nullable=False),
        sa.Column('is_active', sa.Boolean, nullable=False, server_default=sa.text('true')),
        sa.Column('priority', sa.Integer, nullable=False, server_default=sa.text('0')),
        sa.Column('created_at', sa.DateTime, server_default=sa.func.now()),
    )

    # 3. Add profile_id to route_selection_rules
    op.add_column('route_selection_rules', sa.Column('profile_id', sa.BigInteger, nullable=True))
    op.create_foreign_key(
        'fk_route_selection_rules_profile_id',
        'route_selection_rules', 'route_rule_profiles',
        ['profile_id'], ['id']
    )

    # 4. Extend import_templates
    op.add_column('import_templates', sa.Column('code', sa.String(100), nullable=True))
    op.add_column('import_templates', sa.Column('button_label', sa.String(100), nullable=True))
    op.add_column('import_templates', sa.Column('is_active', sa.Boolean, nullable=False, server_default=sa.text('true')))
    op.add_column('import_templates', sa.Column('sort_order', sa.Integer, nullable=False, server_default=sa.text('0')))
    op.add_column('import_templates', sa.Column('route_rule_profile_id', sa.BigInteger, nullable=True))
    op.add_column('import_templates', sa.Column('description', sa.Text, nullable=True))
    op.create_unique_constraint('uq_import_templates_code', 'import_templates', ['code'])
    op.create_foreign_key(
        'fk_import_templates_profile_id',
        'import_templates', 'route_rule_profiles',
        ['route_rule_profile_id'], ['id']
    )

    # 5. Extend import_batches
    op.add_column('import_batches', sa.Column('template_id', sa.BigInteger, nullable=True))
    op.add_column('import_batches', sa.Column('rule_profile_id', sa.BigInteger, nullable=True))
    op.add_column('import_batches', sa.Column('rules_snapshot', JSONB, nullable=False, server_default=sa.text("'[]'::jsonb")))
    op.add_column('import_batches', sa.Column('route_selection_diagnostics', JSONB, nullable=False, server_default=sa.text("'{}'::jsonb")))
    op.create_foreign_key(
        'fk_import_batches_template_id',
        'import_batches', 'import_templates',
        ['template_id'], ['id']
    )
    op.create_foreign_key(
        'fk_import_batches_rule_profile_id',
        'import_batches', 'route_rule_profiles',
        ['rule_profile_id'], ['id']
    )


def downgrade() -> None:
    # 5. Remove import_batches columns
    op.drop_constraint('fk_import_batches_rule_profile_id', 'import_batches', type_='foreignkey')
    op.drop_constraint('fk_import_batches_template_id', 'import_batches', type_='foreignkey')
    op.drop_column('import_batches', 'route_selection_diagnostics')
    op.drop_column('import_batches', 'rules_snapshot')
    op.drop_column('import_batches', 'rule_profile_id')
    op.drop_column('import_batches', 'template_id')

    # 4. Remove import_templates columns
    op.drop_constraint('fk_import_templates_profile_id', 'import_templates', type_='foreignkey')
    op.drop_constraint('uq_import_templates_code', 'import_templates', type_='unique')
    op.drop_column('import_templates', 'description')
    op.drop_column('import_templates', 'route_rule_profile_id')
    op.drop_column('import_templates', 'sort_order')
    op.drop_column('import_templates', 'is_active')
    op.drop_column('import_templates', 'button_label')
    op.drop_column('import_templates', 'code')

    # 3. Remove profile_id from route_selection_rules
    op.drop_constraint('fk_route_selection_rules_profile_id', 'route_selection_rules', type_='foreignkey')
    op.drop_column('route_selection_rules', 'profile_id')

    # 2. Drop route_rule_profiles table
    op.drop_table('route_rule_profiles')

    # 1. Remove code from production_routes
    op.drop_constraint('uq_production_routes_code', 'production_routes', type_='unique')
    op.drop_column('production_routes', 'code')
