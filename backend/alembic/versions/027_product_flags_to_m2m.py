"""Move skip_shot_blast/is_laminated from Product columns to processing_flags M2M (#17, #18).

Data migration: products with skip_shot_blast=True or is_laminated=True get
corresponding ProductProcessingFlag links. Then columns are dropped.
"""
from alembic import op
import sqlalchemy as sa

revision = "027_product_flags_to_m2m"
down_revision = "026_stock_reason_transform_consume"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Ensure ProcessingFlag rows exist
    op.execute("""
        INSERT INTO processing_flags (code, name, section_scope, is_active)
        VALUES ('skip_shot_blast', 'Пропуск дробеструя', 'SHOT_BLAST', true)
        ON CONFLICT (code) DO NOTHING
    """)
    op.execute("""
        INSERT INTO processing_flags (code, name, section_scope, is_active)
        VALUES ('is_laminated', 'Ламинирование', NULL, true)
        ON CONFLICT (code) DO NOTHING
    """)

    # Migrate data: products with skip_shot_blast=True
    op.execute("""
        INSERT INTO product_processing_flags (product_id, flag_id)
        SELECT p.id, f.id
        FROM products p, processing_flags f
        WHERE p.skip_shot_blast = true AND f.code = 'skip_shot_blast'
        ON CONFLICT DO NOTHING
    """)

    # Migrate data: products with is_laminated=True
    op.execute("""
        INSERT INTO product_processing_flags (product_id, flag_id)
        SELECT p.id, f.id
        FROM products p, processing_flags f
        WHERE p.is_laminated = true AND f.code = 'is_laminated'
        ON CONFLICT DO NOTHING
    """)

    # Drop columns
    op.drop_column("products", "skip_shot_blast")
    op.drop_column("products", "is_laminated")


def downgrade() -> None:
    # Re-add columns
    op.add_column("products", sa.Column("skip_shot_blast", sa.Boolean(), server_default=sa.text("false"), nullable=False))
    op.add_column("products", sa.Column("is_laminated", sa.Boolean(), server_default=sa.text("false"), nullable=False))

    # Restore data from M2M
    op.execute("""
        UPDATE products p
        SET skip_shot_blast = true
        FROM product_processing_flags ppf
        JOIN processing_flags f ON f.id = ppf.flag_id
        WHERE ppf.product_id = p.id AND f.code = 'skip_shot_blast'
    """)
    op.execute("""
        UPDATE products p
        SET is_laminated = true
        FROM product_processing_flags ppf
        JOIN processing_flags f ON f.id = ppf.flag_id
        WHERE ppf.product_id = p.id AND f.code = 'is_laminated'
    """)
