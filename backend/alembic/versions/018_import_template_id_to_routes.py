"""add_import_template_id_to_production_routes

Revision ID: 018
Revises: 017_add_route_profile_id
Create Date: 2026-05-31 02:33:20.236748
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa



# revision identifiers, used by Alembic.
revision: str = '018'
down_revision: Union[str, None] = '017_add_route_profile_id'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column('production_routes', sa.Column('import_template_id', sa.BigInteger(), nullable=True))
    op.create_foreign_key(
        'fk_production_routes_import_template_id',
        'production_routes', 'import_templates',
        ['import_template_id'], ['id']
    )


def downgrade() -> None:
    op.drop_constraint('fk_production_routes_import_template_id', 'production_routes', type_='foreignkey')
    op.drop_column('production_routes', 'import_template_id')
