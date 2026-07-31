"""create hrms_employees table

Revision ID: 020_create_hrms_employees
Revises: 019_drop_hrms_tables
Create Date: 2026-07-28

"""
from alembic import op
import sqlalchemy as sa

revision: str = "020_create_hrms_employees"
down_revision: str = "019_drop_hrms_tables"


def upgrade() -> None:
    op.create_table(
        "hrms_employees",
        sa.Column("id", sa.BigInteger, sa.Identity(always=True), primary_key=True, autoincrement=True),
        sa.Column("hrms_id", sa.BigInteger, nullable=False, unique=True),
        sa.Column("name", sa.String(255), nullable=False),
        sa.Column("tab_number", sa.String(50), nullable=True),
        sa.Column("position", sa.String(255), nullable=True),
        sa.Column("department", sa.String(255), nullable=True),
        sa.Column("synced_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
    )


def downgrade() -> None:
    op.drop_table("hrms_employees")
