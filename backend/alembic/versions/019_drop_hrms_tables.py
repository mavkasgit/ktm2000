"""drop hrms_integration_settings, hrms_employee_cache, users.hrms_employee_id

Revision ID: 019_drop_hrms_tables
Revises: 018_remove_hrms_access_level
Create Date: 2026-07-28

"""
from alembic import op

revision: str = "019_drop_hrms_tables"
down_revision: str = "018_remove_hrms_access_level"


def upgrade() -> None:
    op.drop_table("hrms_integration_settings")
    op.drop_table("hrms_employee_cache")
    op.drop_column("users", "hrms_employee_id")


def downgrade() -> None:
    pass
