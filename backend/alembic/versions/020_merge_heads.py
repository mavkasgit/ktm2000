"""merge heads: 018_import_template_id_to_routes + 019_remainder_manual_ops

Revision ID: 020_merge_heads
Revises: 018_import_template_id_to_routes, 019_remainder_manual_ops
Create Date: 2026-06-02 23:30:00.000000
"""

from typing import Sequence, Union

# revision identifiers, used by Alembic.
revision: str = '020_merge_heads'
down_revision: Union[str, tuple, None] = (
    '018',
    '019_remainder_manual_ops',
)
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Pure merge: both parents already applied independently. No SQL needed.
    pass


def downgrade() -> None:
    # Pure merge: nothing to roll back at the schema level.
    pass
