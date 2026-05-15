"""add_excel_passport_to_route_rule_profiles

Revision ID: 014_route_rule_profile_excel_passport
Revises: 013_rule_profiles
Create Date: 2026-05-16 00:30:00.000000
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


# revision identifiers, used by Alembic.
revision: str = "014_route_rule_profile_excel_passport"
down_revision: Union[str, None] = "013_rule_profiles"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "route_rule_profiles",
        sa.Column(
            "excel_column_passport",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default=sa.text("'[]'::jsonb"),
        ),
    )
    op.add_column(
        "route_rule_profiles",
        sa.Column(
            "excel_passport_meta",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
    )


def downgrade() -> None:
    op.drop_column("route_rule_profiles", "excel_passport_meta")
    op.drop_column("route_rule_profiles", "excel_column_passport")

