"""020_storage_vs_production

Adds explicit ``operation_type`` (SectionOperation) and ``stage_kind`` (RouteStage)
to disambiguate storage sections (transit/warehouses) from production sections
(real work centers).  Storage sections become first-class transit nodes between
production stages instead of being smuggled through ``is_significant=False``
heuristics scattered across four different code paths.

Uses TRIGGER-based constraints instead of CHECK constraints because PostgreSQL
CHECK cannot reference other tables (the constraint requires looking up
``sections.kind``).

Revision ID: 020_storage_vs_production
Revises: 019_add_hold
Create Date: 2026-07-01 12:00:00.000000
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "020_storage_vs_production"
down_revision: Union[str, None] = "019_add_hold"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


STAGE_KIND_VALUES = ("production", "transit")
OPERATION_TYPE_VALUES = ("production", "transport")


def _storage_kind_literal() -> str:
    """SQL fragment for ``kind IN ('raw_stock', 'wip_stock', 'finished_stock')``."""
    return "kind IN ('raw_stock', 'wip_stock', 'finished_stock')"


def upgrade() -> None:
    op.execute("COMMIT")
    op.execute(
        "DO $$ BEGIN "
        "IF NOT EXISTS (SELECT 1 FROM pg_type WHERE typname = 'route_stage_kind') THEN "
        "CREATE TYPE route_stage_kind AS ENUM ('production', 'transit'); "
        "END IF; "
        "END $$;"
    )
    op.execute("COMMIT")
    op.execute(
        "DO $$ BEGIN "
        "IF NOT EXISTS (SELECT 1 FROM pg_type WHERE typname = 'section_operation_type') THEN "
        "CREATE TYPE section_operation_type AS ENUM ('production', 'transport'); "
        "END IF; "
        "END $$;"
    )

    op.add_column(
        "section_operations",
        sa.Column(
            "operation_type",
            sa.Enum(
                *OPERATION_TYPE_VALUES,
                name="section_operation_type",
                create_type=False,
            ),
            nullable=False,
            server_default="production",
        ),
    )
    op.add_column(
        "route_stages",
        sa.Column(
            "stage_kind",
            sa.Enum(
                *STAGE_KIND_VALUES,
                name="route_stage_kind",
                create_type=False,
            ),
            nullable=False,
            server_default="production",
        ),
    )
    op.add_column(
        "route_stages",
        sa.Column(
            "storage_section_id",
            sa.BigInteger,
            sa.ForeignKey("sections.id", ondelete="RESTRICT"),
            nullable=True,
        ),
    )

    op.execute(
        """
        UPDATE section_operations so
        SET operation_type = 'transport'
        FROM sections s
        WHERE so.section_id = s.id
          AND s.kind IN ('raw_stock', 'wip_stock', 'finished_stock')
        """
    )

    op.execute(
        """
        UPDATE route_stages rs
        SET stage_kind = 'transit',
            storage_section_id = rs.section_id
        FROM sections s
        WHERE rs.section_id = s.id
          AND s.kind IN ('raw_stock', 'wip_stock', 'finished_stock')
        """
    )

    op.execute(
        """
        DELETE FROM route_operations ro
        USING route_stages rs
        WHERE ro.route_stage_id = rs.id
          AND rs.stage_kind = 'transit'
        """
    )

    # --- TRIGGER: SectionOperation.operation_type='transport' only on storage sections ---
    op.execute(
        """
        CREATE OR REPLACE FUNCTION fn_check_section_op_transport_on_storage()
        RETURNS TRIGGER AS $$
        DECLARE
            sec_kind text;
        BEGIN
            IF NEW.operation_type = 'transport' THEN
                SELECT kind INTO sec_kind FROM sections WHERE id = NEW.section_id;
                IF sec_kind IS NULL OR NOT (sec_kind IN ('raw_stock', 'wip_stock', 'finished_stock')) THEN
                    RAISE EXCEPTION
                        'SectionOperation.operation_type=transport requires Section.kind in (raw_stock|wip_stock|finished_stock); got kind=%, section_id=%',
                        sec_kind, NEW.section_id
                        USING ERRCODE = 'check_violation';
                END IF;
            END IF;
            RETURN NEW;
        END;
        $$ LANGUAGE plpgsql;
        """
    )
    op.execute("DROP TRIGGER IF EXISTS trg_section_op_transport_on_storage ON section_operations;")
    op.execute(
        """
        CREATE TRIGGER trg_section_op_transport_on_storage
        BEFORE INSERT OR UPDATE OF operation_type, section_id ON section_operations
        FOR EACH ROW
        EXECUTE FUNCTION fn_check_section_op_transport_on_storage();
        """
    )

    # --- TRIGGER: RouteStage.stage_kind='transit' requires storage_section_id pointing at storage section ---
    op.execute(
        """
        CREATE OR REPLACE FUNCTION fn_check_route_stage_transit_invariants()
        RETURNS TRIGGER AS $$
        DECLARE
            sec_kind text;
        BEGIN
            IF NEW.stage_kind = 'transit' THEN
                IF NEW.section_id IS NOT NULL THEN
                    RAISE EXCEPTION
                        'RouteStage.stage_kind=transit requires section_id IS NULL; got section_id=%',
                        NEW.section_id
                        USING ERRCODE = 'check_violation';
                END IF;
                IF NEW.storage_section_id IS NULL THEN
                    RAISE EXCEPTION
                        'RouteStage.stage_kind=transit requires storage_section_id IS NOT NULL'
                        USING ERRCODE = 'check_violation';
                END IF;
                SELECT kind INTO sec_kind FROM sections WHERE id = NEW.storage_section_id;
                IF sec_kind IS NULL OR NOT (sec_kind IN ('raw_stock', 'wip_stock', 'finished_stock')) THEN
                    RAISE EXCEPTION
                        'RouteStage.storage_section_id must reference a storage section; got kind=%, storage_section_id=%',
                        sec_kind, NEW.storage_section_id
                        USING ERRCODE = 'check_violation';
                END IF;
            END IF;
            RETURN NEW;
        END;
        $$ LANGUAGE plpgsql;
        """
    )
    op.execute("DROP TRIGGER IF EXISTS trg_route_stage_transit_invariants ON route_stages;")
    op.execute(
        """
        CREATE TRIGGER trg_route_stage_transit_invariants
        BEFORE INSERT OR UPDATE OF stage_kind, section_id, storage_section_id ON route_stages
        FOR EACH ROW
        EXECUTE FUNCTION fn_check_route_stage_transit_invariants();
        """
    )

    op.create_index(
        "ix_route_stages_storage_section_id",
        "route_stages",
        ["storage_section_id"],
    )


def downgrade() -> None:
    op.drop_index("ix_route_stages_storage_section_id", table_name="route_stages")
    op.execute("DROP TRIGGER IF EXISTS trg_route_stage_transit_invariants ON route_stages;")
    op.execute("DROP TRIGGER IF EXISTS trg_section_op_transport_on_storage ON section_operations;")
    op.execute("DROP FUNCTION IF EXISTS fn_check_route_stage_transit_invariants();")
    op.execute("DROP FUNCTION IF EXISTS fn_check_section_op_transport_on_storage();")
    op.drop_column("route_stages", "storage_section_id")
    op.drop_column("route_stages", "stage_kind")
    op.drop_column("section_operations", "operation_type")
    op.execute("DROP TYPE IF EXISTS route_stage_kind")
    op.execute("DROP TYPE IF EXISTS section_operation_type")
