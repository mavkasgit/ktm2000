"""PostgreSQL triggers/functions shared by Alembic migrations and pytest."""

TRIGGER_STATEMENTS: list[str] = [
    """
    CREATE OR REPLACE FUNCTION fn_check_section_op_transport_on_storage()
    RETURNS TRIGGER AS $tg1$
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
    $tg1$ LANGUAGE plpgsql;
    """,
    "DROP TRIGGER IF EXISTS trg_section_op_transport_on_storage ON section_operations;",
    """
    CREATE TRIGGER trg_section_op_transport_on_storage
    BEFORE INSERT OR UPDATE OF operation_type, section_id ON section_operations
    FOR EACH ROW
    EXECUTE FUNCTION fn_check_section_op_transport_on_storage();
    """,
    """
    CREATE OR REPLACE FUNCTION fn_check_route_stage_transit_invariants()
    RETURNS TRIGGER AS $tg2$
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
    $tg2$ LANGUAGE plpgsql;
    """,
    "DROP TRIGGER IF EXISTS trg_route_stage_transit_invariants ON route_stages;",
    """
    CREATE TRIGGER trg_route_stage_transit_invariants
    BEFORE INSERT OR UPDATE OF stage_kind, section_id, storage_section_id ON route_stages
    FOR EACH ROW
    EXECUTE FUNCTION fn_check_route_stage_transit_invariants();
    """,
]

DROP_TRIGGER_STATEMENTS: list[str] = [
    "DROP TRIGGER IF EXISTS trg_route_stage_transit_invariants ON route_stages;",
    "DROP TRIGGER IF EXISTS trg_section_op_transport_on_storage ON section_operations;",
    "DROP FUNCTION IF EXISTS fn_check_route_stage_transit_invariants();",
    "DROP FUNCTION IF EXISTS fn_check_section_op_transport_on_storage();",
]