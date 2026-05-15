"""remove_profile_id_from_import_templates

Revision ID: 016_remove_template_profile_ref
Revises: 015_profile_import_template
Create Date: 2026-05-16 01:00:00.000000
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "016_remove_template_profile_ref"
down_revision: Union[str, None] = "015_profile_import_template"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.drop_constraint("fk_import_templates_profile_id", "import_templates", type_="foreignkey")
    op.drop_column("import_templates", "route_rule_profile_id")


def downgrade() -> None:
    op.add_column(
        "import_templates",
        sa.Column("route_rule_profile_id", sa.BigInteger(), nullable=True),
    )
    op.create_foreign_key(
        "fk_import_templates_profile_id",
        "import_templates",
        "route_rule_profiles",
        ["route_rule_profile_id"],
        ["id"],
    )
