"""add_section_icon_and_color

Revision ID: 003_sections_icon
Revises: 002_techcards_fields
Create Date: 2026-05-04 00:02:00.000000
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '003_sections_icon'
down_revision: Union[str, None] = '002_techcards_fields'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("sections", sa.Column("icon", sa.String(50), nullable=True))
    op.add_column("sections", sa.Column("icon_color", sa.String(7), nullable=True))


def downgrade() -> None:
    op.drop_column("sections", "icon_color")
    op.drop_column("sections", "icon")
