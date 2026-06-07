"""post_factum_transfers

Revision ID: 011_post_factum_transfers
Revises: 010_enforce_unique_section_spg
Create Date: 2026-06-06 20:00:00.000000

Adds the ``is_post_factum`` and ``physical_handover_at`` columns to
``transfers``, and the ``is_post_factum`` column to ``movements``.

This enables recording a cross-GHP transfer after the physical handover
has already taken place and the receiving section has already started
working on the parts: the formal Transfer/Movement rows are still
created (so the cache sums to a consistent value), but they are tagged
as post-factum for audit/history purposes only.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '011_post_factum_transfers'
down_revision: Union[str, None] = '010_enforce_unique_section_spg'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        'transfers',
        sa.Column(
            'is_post_factum',
            sa.Boolean(),
            nullable=False,
            server_default=sa.text('false'),
        ),
    )
    op.add_column(
        'transfers',
        sa.Column(
            'physical_handover_at',
            sa.DateTime(timezone=True),
            nullable=True,
        ),
    )
    op.add_column(
        'movements',
        sa.Column(
            'is_post_factum',
            sa.Boolean(),
            nullable=False,
            server_default=sa.text('false'),
        ),
    )


def downgrade() -> None:
    op.drop_column('movements', 'is_post_factum')
    op.drop_column('transfers', 'physical_handover_at')
    op.drop_column('transfers', 'is_post_factum')
