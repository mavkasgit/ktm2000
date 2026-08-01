"""Move length_mm, weight_per_meter, quantity_per_hanger, cross_section to JSONB attributes (#19, #20).

Data migration: existing column values are merged into the new attributes JSONB column.
Then individual columns are dropped.
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB

revision = "028_product_attributes_jsonb"
down_revision = "027_product_flags_to_m2m"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Add attributes JSONB column
    op.add_column("products", sa.Column("attributes", JSONB, server_default=sa.text("'{}'::jsonb"), nullable=False))

    # Migrate data from columns to JSONB
    op.execute("""
        UPDATE products
        SET attributes = jsonb_strip_nulls(jsonb_build_object(
            'length_mm', length_mm,
            'weight_per_meter', weight_per_meter,
            'quantity_per_hanger', quantity_per_hanger,
            'cross_section', cross_section
        ))
        WHERE length_mm IS NOT NULL
           OR weight_per_meter IS NOT NULL
           OR quantity_per_hanger IS NOT NULL
           OR cross_section IS NOT NULL
    """)

    # Drop individual columns
    op.drop_column("products", "length_mm")
    op.drop_column("products", "weight_per_meter")
    op.drop_column("products", "quantity_per_hanger")
    op.drop_column("products", "cross_section")


def downgrade() -> None:
    # Re-add columns
    op.add_column("products", sa.Column("length_mm", sa.Float(), nullable=True))
    op.add_column("products", sa.Column("weight_per_meter", sa.Float(), nullable=True))
    op.add_column("products", sa.Column("quantity_per_hanger", sa.Integer(), nullable=True))
    op.add_column("products", sa.Column("cross_section", sa.String(100), nullable=True))

    # Restore data from JSONB
    op.execute("""
        UPDATE products
        SET length_mm = (attributes->>'length_mm')::float,
            weight_per_meter = (attributes->>'weight_per_meter')::float,
            quantity_per_hanger = (attributes->>'quantity_per_hanger')::int,
            cross_section = attributes->>'cross_section'
    """)

    # Drop attributes column
    op.drop_column("products", "attributes")
