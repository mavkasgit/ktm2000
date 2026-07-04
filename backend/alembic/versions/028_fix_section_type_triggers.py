"""028_fix_section_type_triggers

После 027 (kind → type) триггеры storage/transit всё ещё читали sections.kind.
Обновляем fn_check_section_op_transport_on_storage и
fn_check_route_stage_transit_invariants на sections.type.

Revision ID: 028_fix_section_type_triggers
Revises: 027_section_unified_type
Create Date: 2026-07-03 24:00:00.000000
"""
from typing import Sequence, Union

from alembic import op

revision: str = "028_fix_section_type_triggers"
down_revision: Union[str, None] = "027_section_unified_type"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute(
        """
        CREATE OR REPLACE FUNCTION fn_check_section_op_transport_on_storage()
        RETURNS TRIGGER AS $$
        DECLARE
            sec_type text;
        BEGIN
            IF NEW.operation_type = 'transport' THEN
                SELECT type INTO sec_type FROM sections WHERE id = NEW.section_id;
                IF sec_type IS NULL OR NOT (sec_type IN ('raw_stock', 'wip_stock', 'finished_stock', 'scrap')) THEN
                    RAISE EXCEPTION
                        'SectionOperation.operation_type=transport requires storage type; got type=%, section_id=%',
                        sec_type, NEW.section_id
                        USING ERRCODE = 'check_violation';
                END IF;
            END IF;
            RETURN NEW;
        END;
        $$ LANGUAGE plpgsql;
        """
    )
    op.execute(
        """
        CREATE OR REPLACE FUNCTION fn_check_route_stage_transit_invariants()
        RETURNS TRIGGER AS $$
        DECLARE
            sec_type text;
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
                SELECT type INTO sec_type FROM sections WHERE id = NEW.storage_section_id;
                IF sec_type IS NULL OR NOT (sec_type IN ('raw_stock', 'wip_stock', 'finished_stock', 'scrap')) THEN
                    RAISE EXCEPTION
                        'RouteStage.storage_section_id must reference a storage section; got type=%, storage_section_id=%',
                        sec_type, NEW.storage_section_id
                        USING ERRCODE = 'check_violation';
                END IF;
            END IF;
            RETURN NEW;
        END;
        $$ LANGUAGE plpgsql;
        """
    )


def downgrade() -> None:
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