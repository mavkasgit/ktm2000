"""добавить dimension_state в products.

Revision ID: 034_product_dimension_state
Revises: 033_product_code
Create Date: 2026-08-08 21:23:37.448050
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = '034_product_dimension_state'
down_revision: str | None = '033_product_code'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    product_dimension_state = sa.Enum('length', 'area', 'volume', name='product_dimension_state')
    product_dimension_state.create(op.get_bind(), checkfirst=True)
    op.add_column('products', sa.Column(
        'dimension_state',
        product_dimension_state,
        server_default=sa.text("'length'"),
        nullable=False,
    ))


def downgrade() -> None:
    op.drop_column('products', 'dimension_state')
    op.execute("DROP TYPE product_dimension_state")
