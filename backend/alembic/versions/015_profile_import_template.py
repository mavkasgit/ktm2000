"""add_import_template_id_to_route_rule_profiles

Revision ID: 015_profile_import_template
Revises: 014_excel_passport
Create Date: 2026-05-15 01:00:00.000000
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "015_profile_import_template"
down_revision: Union[str, None] = "014_excel_passport"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "route_rule_profiles",
        sa.Column(
            "import_template_id",
            sa.BigInteger(),
            nullable=True,
        ),
    )
    op.create_foreign_key(
        "fk_route_rule_profiles_import_template",
        "route_rule_profiles",
        "import_templates",
        ["import_template_id"],
        ["id"],
    )


def downgrade() -> None:
    op.drop_constraint("fk_route_rule_profiles_import_template", "route_rule_profiles", type_="foreignkey")
    op.drop_column("route_rule_profiles", "import_template_id")
