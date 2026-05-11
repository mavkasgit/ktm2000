"""add canonical route signature fields and route signature rules

Revision ID: 006_route_signature_rules
Revises: 005_product_lengths_flags
Create Date: 2026-05-11 13:00:00.000000
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


# revision identifiers, used by Alembic.
revision: str = "006_route_signature_rules"
down_revision: Union[str, None] = "005_product_lengths_flags"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    bind = op.get_bind()
    operation_family_enum = postgresql.ENUM("NONE", "DRILL", "PRESS", "PACK", name="route_operation_family")
    output_kind_enum = postgresql.ENUM("finished_good", "semi_finished_shipment", name="route_output_kind")
    operation_family_enum.create(bind, checkfirst=True)
    output_kind_enum.create(bind, checkfirst=True)

    op.add_column(
        "plan_positions",
        sa.Column(
            "operation_family",
            postgresql.ENUM("NONE", "DRILL", "PRESS", "PACK", name="route_operation_family", create_type=False),
            nullable=True,
        ),
    )
    op.add_column(
        "plan_positions",
        sa.Column(
            "output_kind",
            postgresql.ENUM(
                "finished_good", "semi_finished_shipment", name="route_output_kind", create_type=False
            ),
            nullable=True,
        ),
    )
    op.add_column("plan_positions", sa.Column("has_pack_ops", sa.Boolean(), nullable=True))

    op.create_table(
        "route_signature_rules",
        sa.Column("id", sa.BigInteger(), sa.Identity(always=True), nullable=False),
        sa.Column("route_id", sa.BigInteger(), nullable=False),
        sa.Column(
            "operation_family",
            postgresql.ENUM("NONE", "DRILL", "PRESS", "PACK", name="route_operation_family", create_type=False),
            nullable=False,
        ),
        sa.Column(
            "output_kind",
            postgresql.ENUM(
                "finished_good", "semi_finished_shipment", name="route_output_kind", create_type=False
            ),
            nullable=False,
        ),
        sa.Column("has_pack_ops", sa.Boolean(), nullable=True),
        sa.Column("priority", sa.Integer(), nullable=False, server_default=sa.text("0")),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.text("true")),
        sa.Column("created_at", sa.DateTime(), nullable=True, server_default=sa.text("now()")),
        sa.ForeignKeyConstraint(["route_id"], ["production_routes.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_route_signature_rules_lookup",
        "route_signature_rules",
        ["operation_family", "output_kind", "has_pack_ops", "is_active", "priority"],
        unique=False,
    )

    op.execute(
        """
        UPDATE plan_positions
        SET
            operation_family = CASE
                WHEN upper(coalesce(source_payload->>'operation_code', '')) = 'DRILL' THEN 'DRILL'
                WHEN upper(coalesce(source_payload->>'operation_code', '')) IN ('PRESS', 'PRESS_WINDOW', 'PRESS_COMB') THEN 'PRESS'
                WHEN upper(coalesce(source_payload->>'operation_code', '')) = 'PACK' THEN 'PACK'
                WHEN length(trim(coalesce(source_payload->>'operation', ''))) > 0 THEN 'PACK'
                ELSE 'NONE'
            END::route_operation_family,
            output_kind = CASE
                WHEN source_payload->>'output_kind' = 'finished_good' THEN 'finished_good'
                WHEN source_payload->>'output_kind' = 'semi_finished_shipment' THEN 'semi_finished_shipment'
                ELSE NULL
            END::route_output_kind,
            has_pack_ops = CASE
                WHEN jsonb_typeof(source_payload->'additional_pack_operations') = 'array'
                     AND jsonb_array_length(source_payload->'additional_pack_operations') > 0
                THEN true
                ELSE false
            END
        WHERE source_type = 'excel_import'
        """
    )


def downgrade() -> None:
    op.drop_index("ix_route_signature_rules_lookup", table_name="route_signature_rules")
    op.drop_table("route_signature_rules")
    op.drop_column("plan_positions", "has_pack_ops")
    op.drop_column("plan_positions", "output_kind")
    op.drop_column("plan_positions", "operation_family")

    bind = op.get_bind()
    output_kind_enum = sa.Enum("finished_good", "semi_finished_shipment", name="route_output_kind")
    operation_family_enum = sa.Enum("NONE", "DRILL", "PRESS", "PACK", name="route_operation_family")
    output_kind_enum.drop(bind, checkfirst=True)
    operation_family_enum.drop(bind, checkfirst=True)
