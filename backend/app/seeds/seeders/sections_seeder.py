from __future__ import annotations

from sqlalchemy.ext.asyncio import AsyncSession

from app.models.route import SectionOperation
from app.models.section import Section
from app.seeds.canon.models import OperationDef, ProductionCanon, SectionDef
from app.seeds.sections import SECTION_OPERATIONS_FIELD_MAP, SECTIONS_FIELD_MAP
from app.seeds.upsert import upsert_by_key


async def seed_sections(
    db: AsyncSession,
    sections: list[SectionDef],
) -> dict[str, Section]:
    """Upsert all sections by code. Returns {code: section} map.

    Данные приходят всегда явно из run_seed (типизированный канон);
    никаких скрытых дефолтов и backward-compat веток.
    """
    return await upsert_by_key(
        db,
        Section,
        sections,
        key_field="code",
        field_map=SECTIONS_FIELD_MAP,
    )


async def seed_section_operations(
    db: AsyncSession,
    sections_map: dict[str, Section],
    production: ProductionCanon,
) -> int:
    """Upsert SectionOperation records for each section. Returns count.

    Составной ключ (section_id, operation_code) вычисляется до вызова хелпера:
    section_id — из sections_map, transforms_dimensions — из transforming_ops.
    """
    transforming_set = {
        (ref.section_code, ref.operation_code)
        for ref in production.transforming_ops
    }

    def resolve(op: OperationDef) -> dict:
        return {
            "section_id": sections_map[op.section_code].id,
            "transforms_dimensions": (op.section_code, op.operation_code) in transforming_set,
        }

    # Skip placeholder operations (operation_code=None) и операции
    # с неизвестной секцией — как в исходном седере.
    rows = [
        op
        for op in production.ops
        if op.operation_code is not None and op.section_code in sections_map
    ]

    result = await upsert_by_key(
        db,
        SectionOperation,
        rows,
        key_field=("section_id", "operation_code"),
        field_map=SECTION_OPERATIONS_FIELD_MAP,
        resolve=resolve,
    )
    return len(result)
