"""add_hrms_access_level

Revision ID: 016_add_hrms_access_level
Revises: 015_add_employee_fields_to_user
Create Date: 2026-06-17 00:36:56.634268
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '016_add_hrms_access_level'
down_revision: Union[str, None] = '015_add_employee_fields_to_user'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column('users', sa.Column('hrms_access_level', sa.String(length=50), server_default=sa.text("'no_access'"), nullable=False))


def downgrade() -> None:
    op.drop_column('users', 'hrms_access_level')
