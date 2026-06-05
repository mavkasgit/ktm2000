"""defects_refactoring

Revision ID: 009_defects_refactoring
Revises: 008_comments_and_attachments
Create Date: 2026-06-05 16:04:21.635134
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa



# revision identifiers, used by Alembic.
revision: str = '009_defects_refactoring'
down_revision: Union[str, None] = '008_comments_and_attachments'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # 1. Make task_id nullable
    op.alter_column('defects', 'task_id', nullable=True)
    
    # 2. Add route_stage_id FK
    op.add_column('defects', sa.Column('route_stage_id', sa.BigInteger(), sa.ForeignKey('route_stages.id', ondelete='SET NULL'), nullable=True))
    
    # 3. Add spg_remainder_id FK
    op.add_column('defects', sa.Column('spg_remainder_id', sa.BigInteger(), sa.ForeignKey('spg_remainders.id', ondelete='SET NULL'), nullable=True))


def downgrade() -> None:
    # 1. Drop columns
    op.drop_column('defects', 'spg_remainder_id')
    op.drop_column('defects', 'route_stage_id')
    
    # 2. Make task_id non-nullable again
    op.alter_column('defects', 'task_id', nullable=False)
