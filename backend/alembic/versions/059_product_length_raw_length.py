"""Добавить сырьевую длину к каноническому реестру product_lengths.

Revision ID: 059_product_length_raw_length
Revises: 058_product_pair_quantity_norms
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op


revision: str = "059_product_length_raw_length"
down_revision: Union[str, None] = "058_product_pair_quantity_norms"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

CHECK_CONSTRAINT_NAME = "raw_length_mm_at_least_length_mm"
ORM_CHECK_CONSTRAINT_NAME = "ck_product_lengths_raw_length_mm_at_least_length_mm"


def upgrade() -> None:
    bind = op.get_bind()

    conflicts = bind.execute(
        sa.text(
            """
            WITH canonical AS (
                SELECT
                    p.id AS product_id,
                    p.sku,
                    COALESCE(
                        (
                            SELECT pl.length_mm
                            FROM product_lengths pl
                            WHERE pl.product_id = p.id
                            ORDER BY pl.is_primary DESC, pl.length_mm ASC, pl.id ASC
                            LIMIT 1
                        ),
                        CASE
                            WHEN jsonb_typeof(p.attributes->'length_mm') = 'number'
                            THEN (p.attributes->>'length_mm')::double precision
                        END
                    ) AS normal_length
                FROM products p
                WHERE p.dimension_state = 'length'
            )
            SELECT c.sku, pd.default_value, c.normal_length
            FROM canonical c
            JOIN product_dimensions pd ON pd.product_id = c.product_id
            JOIN dimension_types dt ON dt.id = pd.dimension_type_id
            WHERE dt.code = 'length_mm'
              AND pd.default_value IS NOT NULL
              AND c.normal_length IS NOT NULL
              AND pd.default_value <> c.normal_length
            ORDER BY c.sku
            """
        )
    ).mappings().all()
    if conflicts:
        details = ", ".join(
            f"{row['sku']}: default={float(row['default_value']):g}, "
            f"primary={float(row['normal_length']):g}"
            for row in conflicts
        )
        raise RuntimeError(
            "product_dimensions.default_value conflicts with the canonical normal "
            f"length; resolve these values manually before retrying: {details}"
        )

    columns = {column["name"] for column in sa.inspect(bind).get_columns("product_lengths")}
    if "raw_length_mm" not in columns:
        op.add_column("product_lengths", sa.Column("raw_length_mm", sa.Float(), nullable=True))

    # Backfill only products with no canonical registry row. A legacy scalar is
    # never converted (in particular, 2750 is not rewritten to 2700).
    op.execute(
        sa.text(
            """
            INSERT INTO product_lengths (product_id, length_mm, is_primary, raw_length_mm)
            SELECT p.id, (p.attributes->>'length_mm')::double precision, true, NULL
            FROM products p
            WHERE p.dimension_state = 'length'
              AND p.attributes ? 'length_mm'
              AND (p.attributes->>'length_mm')::double precision > 0
              AND NOT EXISTS (
                  SELECT 1 FROM product_lengths pl WHERE pl.product_id = p.id
              )
            """
        )
    )

    constraints = {
        constraint.get("name")
        for constraint in sa.inspect(bind).get_check_constraints("product_lengths")
    }
    # Alembic-created databases may already have the legacy unprefixed name;
    # ORM create_all uses SQLAlchemy's conventional prefixed name.
    if not constraints.intersection(
        {CHECK_CONSTRAINT_NAME, ORM_CHECK_CONSTRAINT_NAME}
    ):
        op.create_check_constraint(
            CHECK_CONSTRAINT_NAME,
            "product_lengths",
            "raw_length_mm IS NULL OR raw_length_mm >= length_mm",
        )

    # A matching legacy default has no runtime role after the canonical registry
    # exists. Conflicting values were rejected before any DDL above.
    op.execute(
        sa.text(
            """
            WITH canonical AS (
                SELECT
                    p.id AS product_id,
                    (
                        SELECT pl.length_mm
                        FROM product_lengths pl
                        WHERE pl.product_id = p.id
                        ORDER BY pl.is_primary DESC, pl.length_mm ASC, pl.id ASC
                        LIMIT 1
                    ) AS normal_length
                FROM products p
                WHERE p.dimension_state = 'length'
            )
            UPDATE product_dimensions pd
            SET default_value = NULL
            FROM dimension_types dt, canonical c
            WHERE pd.product_id = c.product_id
              AND dt.id = pd.dimension_type_id
              AND dt.code = 'length_mm'
              AND pd.default_value IS NOT NULL
              AND c.normal_length IS NOT NULL
              AND pd.default_value = c.normal_length
            """
        )
    )


def downgrade() -> None:
    bind = op.get_bind()
    constraints = {
        constraint.get("name")
        for constraint in sa.inspect(bind).get_check_constraints("product_lengths")
    }
    for constraint_name in constraints.intersection(
        {CHECK_CONSTRAINT_NAME, ORM_CHECK_CONSTRAINT_NAME}
    ):
        quoted_name = bind.dialect.identifier_preparer.quote(constraint_name)
        op.execute(
            sa.text(f"ALTER TABLE product_lengths DROP CONSTRAINT {quoted_name}")
        )
    columns = {
        column["name"]
        for column in sa.inspect(bind).get_columns("product_lengths")
    }
    if "raw_length_mm" in columns:
        op.drop_column("product_lengths", "raw_length_mm")
