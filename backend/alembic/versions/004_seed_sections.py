"""seed_sections

Revision ID: 004_seed_sections
Revises: 003_sections_icon
Create Date: 2026-05-04 00:03:00.000000
"""

from typing import Sequence, Union

from alembic import op


# revision identifiers, used by Alembic.
revision: str = '004_seed_sections'
down_revision: Union[str, None] = '003_sections_icon'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Sections data is now seeded via app.seeds.run_seed
    pass


def downgrade() -> None:
    # Sections data removal handled by re-running seeders
    pass
