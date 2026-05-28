"""remove seed data — reference data should be seeded via run_full_seed, not migrations.

Revision ID: 009_seed_data
Revises: 008_final_polish
Create Date: 2026-05-25 12:07:00.000000
"""

from typing import Sequence, Union

from alembic import op


revision: str = '009_seed_data'
down_revision: Union[str, None] = '008_final_polish'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
