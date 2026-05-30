"""drop operation_family, output_kind columns and enum types

Revision ID: 013_drop_route_routing_enums
Revises: 012_resolver_type
Create Date: 2026-05-30
"""
from alembic import op
import sqlalchemy as sa

revision = "013_drop_route_routing_enums"
down_revision = "012_resolver_type"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Drop columns from plan_positions (created in 004)
    op.drop_column("plan_positions", "output_kind")
    op.drop_column("plan_positions", "operation_family")

    # Drop columns from route_matching_rules (created in 005)
    op.drop_column("route_matching_rules", "output_kind")
    op.drop_column("route_matching_rules", "operation_family")

    # Drop columns from route_signature_rules (created in 005)
    op.drop_index("ix_route_signature_rules_lookup", table_name="route_signature_rules")
    op.drop_column("route_signature_rules", "output_kind")
    op.drop_column("route_signature_rules", "operation_family")
    op.create_index(
        "ix_route_signature_rules_lookup",
        "route_signature_rules",
        ["has_pack_ops", "is_active", "priority"],
    )

    # Drop enum types
    sa.Enum(name="route_output_kind").drop(op.get_bind(), checkfirst=True)
    sa.Enum(name="route_operation_family").drop(op.get_bind(), checkfirst=True)


def downgrade() -> None:
    # Recreate enum types
    op.execute(
        "CREATE TYPE route_operation_family AS ENUM ('NONE', 'DRILL', 'PRESS', 'PACK', 'SPUNBOND', 'STRETCH')"
    )
    op.execute("CREATE TYPE route_output_kind AS ENUM ('finished_good', 'semi_finished_shipment')")

    # Recreate columns in route_signature_rules
    op.drop_index("ix_route_signature_rules_lookup", table_name="route_signature_rules")
    op.add_column(
        "route_signature_rules",
        sa.Column("operation_family", sa.Enum("NONE", "DRILL", "PRESS", "PACK", "SPUNBOND", "STRETCH", name="route_operation_family"), nullable=False, server_default="NONE"),
    )
    op.add_column(
        "route_signature_rules",
        sa.Column("output_kind", sa.Enum("finished_good", "semi_finished_shipment", name="route_output_kind"), nullable=False, server_default="finished_good"),
    )
    op.create_index(
        "ix_route_signature_rules_lookup",
        "route_signature_rules",
        ["operation_family", "output_kind", "has_pack_ops", "is_active", "priority"],
    )

    # Recreate columns in route_matching_rules
    op.add_column(
        "route_matching_rules",
        sa.Column("operation_family", sa.Enum("NONE", "DRILL", "PRESS", "PACK", "SPUNBOND", "STRETCH", name="route_operation_family"), nullable=False),
    )
    op.add_column(
        "route_matching_rules",
        sa.Column("output_kind", sa.Enum("finished_good", "semi_finished_shipment", name="route_output_kind"), nullable=False),
    )

    # Recreate columns in plan_positions
    op.add_column(
        "plan_positions",
        sa.Column("operation_family", sa.Enum("NONE", "DRILL", "PRESS", "PACK", "SPUNBOND", "STRETCH", name="route_operation_family"), nullable=True),
    )
    op.add_column(
        "plan_positions",
        sa.Column("output_kind", sa.Enum("finished_good", "semi_finished_shipment", name="route_output_kind"), nullable=True),
    )
