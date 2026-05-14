"""add exact press semi-finished signature rules

Revision ID: 010_press_semi_exact_rules
Revises: 009_route_origin_metadata
Create Date: 2026-05-14 21:55:00
"""

from typing import Sequence, Union

from alembic import op


revision: str = "010_press_semi_exact_rules"
down_revision: Union[str, None] = "009_route_origin_metadata"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute(
        """
        WITH source_rule AS (
            SELECT rsr.route_id, rsr.priority
            FROM route_signature_rules rsr
            WHERE rsr.is_active IS TRUE
              AND rsr.operation_family = 'PRESS'::route_operation_family
              AND rsr.output_kind = 'semi_finished_shipment'::route_output_kind
              AND rsr.has_pack_ops IS NULL
            ORDER BY rsr.priority DESC, rsr.id ASC
            LIMIT 1
        ),
        source_route AS (
            SELECT route_id, priority
            FROM source_rule
            UNION ALL
            SELECT pr.id AS route_id, 100 AS priority
            FROM production_routes pr
            WHERE pr.is_active IS TRUE
              AND pr.name = 'Типовой: П/ф с прессом'
              AND NOT EXISTS (SELECT 1 FROM source_rule)
        )
        INSERT INTO route_signature_rules (
            route_id,
            operation_family,
            output_kind,
            has_pack_ops,
            priority,
            is_active
        )
        SELECT
            sr.route_id,
            'PRESS'::route_operation_family,
            'semi_finished_shipment'::route_output_kind,
            vals.has_pack_ops,
            sr.priority,
            TRUE
        FROM source_route sr
        CROSS JOIN (VALUES (FALSE), (TRUE)) AS vals(has_pack_ops)
        WHERE NOT EXISTS (
            SELECT 1
            FROM route_signature_rules existing
            WHERE existing.route_id = sr.route_id
              AND existing.operation_family = 'PRESS'::route_operation_family
              AND existing.output_kind = 'semi_finished_shipment'::route_output_kind
              AND existing.has_pack_ops IS NOT DISTINCT FROM vals.has_pack_ops
              AND existing.is_active IS TRUE
        )
        """
    )


def downgrade() -> None:
    # Irreversible data migration: avoid deleting potentially valid exact rules.
    pass
