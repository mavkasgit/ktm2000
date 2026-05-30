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
    op.execute("ALTER TABLE plan_positions DROP COLUMN IF EXISTS output_kind")
    op.execute("ALTER TABLE plan_positions DROP COLUMN IF EXISTS operation_family")

    # Drop columns from route_matching_rules (created in 005)
    op.execute("ALTER TABLE route_matching_rules DROP COLUMN IF EXISTS output_kind")
    op.execute("ALTER TABLE route_matching_rules DROP COLUMN IF EXISTS operation_family")

    # Drop columns from route_signature_rules (created in 005)
    op.execute("ALTER TABLE route_signature_rules DROP COLUMN IF EXISTS output_kind")
    op.execute("ALTER TABLE route_signature_rules DROP COLUMN IF EXISTS operation_family")
    # Recreate index without dropped columns
    op.execute("DROP INDEX IF EXISTS ix_route_signature_rules_lookup")
    op.create_index(
        "ix_route_signature_rules_lookup",
        "route_signature_rules",
        ["has_pack_ops", "is_active", "priority"],
    )

    # Drop enum types
    op.execute("DROP TYPE IF EXISTS route_output_kind")
    op.execute("DROP TYPE IF EXISTS route_operation_family")


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
