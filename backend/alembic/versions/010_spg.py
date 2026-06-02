"""add storage_production_groups and spg_sections tables.

Revision ID: 010_spg
Revises: 009_seed_data
Create Date: 2026-06-02 10:00:00.000000
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = '010_spg'
down_revision: Union[str, None] = '009_seed_data'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        'storage_production_groups',
        sa.Column('id', sa.BigInteger, sa.Identity(always=True), primary_key=True),
        sa.Column('code', sa.String(100), nullable=False, unique=True),
        sa.Column('name', sa.String(255), nullable=False),
        sa.Column('description', sa.Text, nullable=True),
        sa.Column('sort_order', sa.Integer, nullable=False, server_default='0'),
        sa.Column('is_active', sa.Boolean, nullable=False, server_default='true'),
        sa.Column('icon', sa.String(50), nullable=True),
        sa.Column('icon_color', sa.String(7), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
    )

    op.create_table(
        'spg_sections',
        sa.Column('id', sa.BigInteger, sa.Identity(always=True), primary_key=True),
        sa.Column('spg_id', sa.BigInteger, sa.ForeignKey('storage_production_groups.id', ondelete='CASCADE'), nullable=False),
        sa.Column('section_id', sa.BigInteger, sa.ForeignKey('sections.id', ondelete='CASCADE'), nullable=False),
        sa.Column('sort_order', sa.Integer, nullable=False, server_default='0'),
        sa.UniqueConstraint('spg_id', 'section_id', name='uq_spg_sections'),
    )


def downgrade() -> None:
    op.drop_table('spg_sections')
    op.drop_table('storage_production_groups')
