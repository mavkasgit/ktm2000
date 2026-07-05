"""hrms

Эпик: Интеграция HRMS: кэш сотрудников и настройки
Irreversible: no

Revision ID: 011_hrms
Revises: 010_collaboration_and_audit
Create Date: 2026-07-05 19:00:00.000000
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision: str = "011_hrms"
down_revision: Union[str, None] = "010_collaboration_and_audit"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # --- SCHEMA ---
    op.create_table('hrms_employee_cache',
    sa.Column('hrms_id', sa.BigInteger(), nullable=False),
    sa.Column('name', sa.String(length=255), nullable=False),
    sa.Column('tab_number', sa.String(length=50), nullable=True),
    sa.Column('position', sa.String(length=255), nullable=True),
    sa.Column('department', sa.String(length=255), nullable=True),
    sa.Column('synced_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.PrimaryKeyConstraint('hrms_id', name=op.f('pk_hrms_employee_cache'))
    )
    op.create_table('hrms_integration_settings',
    sa.Column('id', sa.BigInteger(), sa.Identity(always=True), autoincrement=True, nullable=False),
    sa.Column('base_url', sa.String(length=512), nullable=True),
    sa.Column('api_token', sa.String(length=255), server_default=sa.text("'admin'"), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_hrms_integration_settings'))
    )

    # --- DATA ---
    pass

    # --- TRIGGERS ---
    pass


def downgrade() -> None:
    op.drop_table('hrms_integration_settings')
    op.drop_table('hrms_employee_cache')
