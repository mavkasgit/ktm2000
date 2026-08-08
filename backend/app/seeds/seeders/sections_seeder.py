from __future__ import annotations

from sqlalchemy.ext.asyncio import AsyncSession

from app.models.route import SectionOperation
from app.models.section import Section
from app.seeds.canon.models import OperationDef, ProductionCanon, SectionDef
from app.seeds.canon.registry import build_plant_config
from app.seeds.upsert import upsert_by_code

# Типизированный канон (ADR-0004/0008 carve-out): единственный конвертер
# сырых данных → моделей живёт в registry; седер использует его результат
# для дефолтного значения (backward-compat для прямых вызовов седера).
_DEFAULT_PRODUCTION = build_plant_config().production

SECTIONS_FIELD_MAP = {
    "code": "code",
    "name": "name",
    "sort_order": "sort_order",
    "type": "type",
    "icon": "icon",
    "icon_color": "icon_color",
    "is_active": "is_active",
}

SECTION_OPERATIONS_FIELD_MAP = {
    "operation_code": "operation_code",
    "operation_name": "operation_name",
    "is_significant": "is_significant",
    "icon": "icon",
    "icon_color": "icon_color",
    "group_code": "group_code",
    "group_name": "group_name",
    "sort_order": "sort_order",
    "resolver_type": "resolver_type",
    "resolver_config": "resolver_config",
    "operation_type": "operation_type",
}


async def seed_sections(
    db: AsyncSession,
    sections: list[SectionDef] | None = None,
    force: bool = False,
) -> dict[str, Section]:
    """Upsert all sections by code. Returns {code: section} map."""
    if sections is None:
        sections = _DEFAULT_PRODUCTION.sections

    return await upsert_by_code(
        db,
        Section,
        sections,
        key_field="code",
        field_map=SECTIONS_FIELD_MAP,
    )


async def seed_section_operations(
    db: AsyncSession,
    sections_map: dict[str, Section],
    production: ProductionCanon | None = None,
) -> int:
    """Upsert SectionOperation records for each section. Returns count.

    Составной ключ (section_id, operation_code) вычисляется до вызова хелпера:
    section_id — из sections_map, transforms_dimensions — из transforming_ops.
    """
    if production is None:
        production = _DEFAULT_PRODUCTION

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

    result = await upsert_by_code(
        db,
        SectionOperation,
        rows,
        key_field=("section_id", "operation_code"),
        field_map=SECTION_OPERATIONS_FIELD_MAP,
        resolve=resolve,
    )
    return len(result)
