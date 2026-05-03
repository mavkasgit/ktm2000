"""product_aliases_and_skip_shot_blast

Revision ID: 002_product_aliases
Revises: 89fd6a7d5f21
Create Date: 2026-05-03 16:00:00
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "002_product_aliases"
down_revision: Union[str, None] = "540f33c479b8"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("products", sa.Column("skip_shot_blast", sa.Boolean(), server_default=sa.text("false"), nullable=False))
    op.add_column("products", sa.Column("aliases", sa.ARRAY(sa.String()), server_default=sa.text("'{}'"), nullable=False))


def downgrade() -> None:
    op.drop_column("products", "aliases")
    op.drop_column("products", "skip_shot_blast")
