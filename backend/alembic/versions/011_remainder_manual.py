"""make warehouse remainder FKs nullable and add source column for manual inventory.

Revision ID: 011_remainder_manual
Revises: 010_spg
Create Date: 2026-06-02 12:00:00.000000
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = '011_remainder_manual'
down_revision: Union[str, None] = '010_spg'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Make FK columns nullable
    op.alter_column('warehouse_remainders', 'route_step_id',
                    existing_type=sa.BigInteger, nullable=True)
    op.alter_column('warehouse_remainders', 'section_plan_line_id',
                    existing_type=sa.BigInteger, nullable=True)
    op.alter_column('warehouse_remainders', 'origin_task_id',
                    existing_type=sa.BigInteger, nullable=True)

    # Add source column
    op.add_column('warehouse_remainders',
                  sa.Column('source', sa.String(20), nullable=False, server_default='task'))


def downgrade() -> None:
    op.drop_column('warehouse_remainders', 'source')

    op.alter_column('warehouse_remainders', 'origin_task_id',
                    existing_type=sa.BigInteger, nullable=False)
    op.alter_column('warehouse_remainders', 'section_plan_line_id',
                    existing_type=sa.BigInteger, nullable=False)
    op.alter_column('warehouse_remainders', 'route_step_id',
                    existing_type=sa.BigInteger, nullable=False)
