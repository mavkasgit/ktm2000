"""enforce_unique_section_spg

Revision ID: 010_enforce_unique_section_spg
Revises: 009_defects_refactoring
Create Date: 2026-06-06 04:54:00.000000
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '010_enforce_unique_section_spg'
down_revision: Union[str, None] = '009_defects_refactoring'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # 1. Clean up duplicate section links (keep only the link with the smallest spg_id)
    op.execute(
        """
        DELETE FROM spg_sections
        WHERE id NOT IN (
            SELECT MIN(id)
            FROM spg_sections
            GROUP BY section_id
        )
        """
    )
    
    # 2. Add Unique Constraint on section_id
    op.create_unique_constraint('uq_spg_sections_section_id', 'spg_sections', ['section_id'])


def downgrade() -> None:
    # Drop Unique Constraint
    op.drop_constraint('uq_spg_sections_section_id', 'spg_sections', type_='unique')
