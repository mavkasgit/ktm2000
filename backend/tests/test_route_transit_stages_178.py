"""Складские шаги маршрута — транзит-хопы в обоих путях (#178).

Маршрут, собранный импортом плана, материализовал каждый шаг как
``RouteStage(section_id=<секция шага>)`` — склад получался этаром
``production``, то есть цехом. Сидер (``routes_seeder``) и билдер
(``route_builder``)склады делают транзит-хопом: ``stage_kind=transit``,
``section_id IS NULL``, ``storage_section_id=<склад>``. Расхождение ломало
потребителей ``is_transit_stage``: ``resolve_final_release_destination``
не находил хоп маршрута, авто-передачи обрывались на «цехе», а подбор
маршрута (``load_route_sections`` джойнил только ``RouteStage.section_id``)
терял складские шаги целиком.

Покрывают:
- импорт плана материализует складские/терминальные шаги как транзит-хопы;
- набор этапов импортированного маршрута совпадает с сидером по тому же
  профилю (паритет двух путей);
- адресат финального выпуска берётся из контекста маршрута (каскад #137),
  а не из глобального ``is_output_default``;
- складской шаг не теряется из подбора маршрута — с кэшем батча и без.
"""
from __future__ import annotations

from io import BytesIO

import pytest
from app.models.import_template import ImportTemplate
from app.models.route import (
    ProductionRoute,
    RouteRuleProfile,
    RouteSelectionRule,
    RouteStage,
    SectionOperation,
)
from app.models.section import Section
from app.seeds.seeders.routes_seeder import seed_production_routes_from_profiles
from app.services.plan_import_service import create_excel_import_change_set
from app.services.route_selection import (
    load_route_sections,
    load_route_selection_batch_cache,
    select_route_for_payload,
)
from app.services.shopfloor.operations_tasks import resolve_final_release_destination
from openpyxl import Workbook
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from tests.plan_sample import HEADERS, build_sample_plan_rows

# Топология профиля: два цеха и два склада в конце маршрута — склад ГП и
# терминал «Отправлено». ``FG_DEFAULT`` — отдельный склад ГП с
# ``is_output_default``, чтобы отличить адресат из маршрута от глобального
# фолбэка каскада #137.
PROFILE_SECTIONS = [
    {"code": "ANODIZING", "name": "Анодирование", "sort_order": 50, "type": "production"},
    {"code": "PACKING", "name": "Упаковка", "sort_order": 80, "type": "production"},
    {"code": "FINISHED_STOCK", "name": "Склад готовой продукции", "sort_order": 90, "type": "finished_stock"},
    {"code": "SHIPPED", "name": "Отправлено", "sort_order": 110, "type": "terminal"},
]
ROUTE_SECTION_CODES = ["ANODIZING", "PACKING", "FINISHED_STOCK", "SHIPPED"]


def _one_row_workbook() -> bytes:
    """Сэмпл-план из одной строки (заголовки как у упаковочного плана)."""
    wb = Workbook()
    ws = wb.active
    assert ws is not None
    ws.title = "totalplan"
    for _ in range(3):
        ws.append([])
    ws.append(list(HEADERS))
    ws.append(build_sample_plan_rows()[0])
    out = BytesIO()
    wb.save(out)
    return out.getvalue()


class _Ctx178:
    def __init__(self) -> None:
        self.sections: dict[str, Section] = {}
        self.profile: RouteRuleProfile | None = None
        self.template: ImportTemplate | None = None


async def _seed_178(session: AsyncSession) -> _Ctx178:
    ctx = _Ctx178()
    for spec in PROFILE_SECTIONS:
        section = Section(
            code=spec["code"],
            name=spec["name"],
            sort_order=spec["sort_order"],
            type=spec["type"],
            is_active=True,
        )
        session.add(section)
        await session.flush()
        ctx.sections[spec["code"]] = section
    # Склад-фолбэк каскада #137: не участвует в маршруте профиля.
    fallback = Section(
        code="FG_DEFAULT", name="Склад ГП (по умолчанию)", sort_order=95,
        type="finished_stock", is_active=True, is_output_default=True,
    )
    session.add(fallback)
    await session.flush()
    ctx.sections["FG_DEFAULT"] = fallback

    session.add_all([
        SectionOperation(
            section_id=ctx.sections["ANODIZING"].id, operation_code="ANOD_01",
            operation_name="Серебро", group_code="ANOD", group_name="Анодирование",
            sort_order=10, is_significant=True, operation_type="production",
        ),
        SectionOperation(
            section_id=ctx.sections["PACKING"].id, operation_code="PACK_STRETCH",
            operation_name="Стретч", group_code="PACK", group_name="Упаковка",
            sort_order=10, is_significant=True, operation_type="production",
        ),
    ])
    ctx.template = ImportTemplate(code="tpl178", name="Шаблон 178", is_active=True)
    session.add(ctx.template)
    await session.flush()

    ctx.profile = RouteRuleProfile(
        code="profile178",
        name="Профиль 178",
        is_active=True,
        priority=100,
        import_template_id=ctx.template.id,
        route_sections=list(ROUTE_SECTION_CODES),
    )
    session.add(ctx.profile)
    await session.flush()

    session.add_all([
        RouteSelectionRule(
            code="core178", name="core", profile_id=ctx.profile.id, priority=1000,
            is_active=True, phase="route_select", conditions=[],
            actions=[
                {"action": "require_section", "section_code": code}
                for code in ROUTE_SECTION_CODES
            ],
        ),
        RouteSelectionRule(
            code="anod178", name="anod", profile_id=ctx.profile.id, priority=100,
            is_active=True, phase="resolve_operations",
            conditions=[{"source": "payload", "field_path": "color",
                         "operator": "not_empty", "value": None}],
            actions=[{
                "action": "set_operation_by_mapping", "section_code": "ANODIZING",
                "group_code": "ANOD", "lookup_field": "color",
                "mapping": [{"keyword": "серебр", "operation_code": "ANOD_01"}],
            }],
        ),
    ])
    await session.flush()
    return ctx


async def _stage_rows(session: AsyncSession, route_id: int) -> list[RouteStage]:
    return list(
        (
            await session.execute(
                select(RouteStage)
                .where(RouteStage.route_id == route_id)
                .order_by(RouteStage.sequence)
            )
        ).scalars().all()
    )


async def _import_route(session: AsyncSession, ctx: _Ctx178) -> ProductionRoute:
    """Импорт одной строки плана → ProductionRoute, собранный по профилю."""
    await create_excel_import_change_set(
        session,
        filename="plan-178.xlsx",
        content=_one_row_workbook(),
        content_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        template_id=ctx.template.id,
        rule_profile_id=ctx.profile.id,
    )
    route = await session.scalar(
        select(ProductionRoute)
        .where(ProductionRoute.name != f"Dynamic: {ctx.profile.name}")
        .order_by(ProductionRoute.id.desc())
    )
    assert route is not None, "импорт не материализовал маршрут"
    return route


async def _stage_signature(session: AsyncSession, route_id: int) -> list[tuple]:
    """(sequence, stage_kind, код секции) по этапам маршрута."""
    signature = []
    for stage in await _stage_rows(session, route_id):
        section_id = stage.storage_section_id if stage.is_transit else stage.section_id
        section = await session.get(Section, section_id) if section_id else None
        signature.append((stage.sequence, stage.stage_kind, section.code if section else None))
    return signature


# ─── импорт: складские шаги — транзит-хопы ───────────────────────────────────


@pytest.mark.asyncio
async def test_import_materializes_storage_steps_as_transit_hops(session: AsyncSession) -> None:
    """Склад и терминал импортированного маршрута — транзит, а не цех."""
    ctx = await _seed_178(session)
    route = await _import_route(session, ctx)
    stages = await _stage_rows(session, route.id)

    assert len(stages) == len(ROUTE_SECTION_CODES)
    for stage, code in zip(stages, ROUTE_SECTION_CODES, strict=True):
        section = ctx.sections[code]
        if section.type == "production":
            assert (stage.stage_kind, stage.section_id) == ("production", section.id)
            assert stage.storage_section_id is None
        else:
            assert (stage.stage_kind, stage.section_id) == ("transit", None)
            assert stage.storage_section_id == section.id


@pytest.mark.asyncio
async def test_imported_route_stages_match_seeder_for_same_profile(session: AsyncSession) -> None:
    """Паритет путей: импорт и сид дают одинаковый набор этапов профиля."""
    ctx = await _seed_178(session)
    imported = await _import_route(session, ctx)

    await seed_production_routes_from_profiles(
        session, dict(ctx.sections)
    )
    seeded = await session.scalar(
        select(ProductionRoute).where(ProductionRoute.name == f"Dynamic: {ctx.profile.name}")
    )
    assert seeded is not None

    imported_signature = await _stage_signature(session, imported.id)
    seeded_signature = await _stage_signature(session, seeded.id)

    # Финальность этапов у путей разная по правилу (сид — «SHIPPED», импорт —
    # последний шаг билдера), поэтому паритет проверяется по участку и виду этапа.
    assert imported_signature == seeded_signature


# ─── каскад адресата финального выпуска (#137) ───────────────────────────────


@pytest.mark.asyncio
async def test_final_release_destination_uses_route_hop_over_global_default(
    session: AsyncSession,
) -> None:
    """Адресат выпуска — складский хоп маршрута, а не глобальный дефолт."""
    ctx = await _seed_178(session)
    route = await _import_route(session, ctx)
    stages = await _stage_rows(session, route.id)
    packing = next(s for s in stages if s.section_id == ctx.sections["PACKING"].id)

    destination = await resolve_final_release_destination(session, packing)

    assert destination.code == "FINISHED_STOCK"
    assert destination.id == ctx.sections["FINISHED_STOCK"].id


# ─── подбор маршрута: складские шаги не теряются ────────────────────────────


@pytest.mark.asyncio
async def test_route_selection_sees_transit_hop_sections_with_and_without_cache(
    session: AsyncSession,
) -> None:
    """Правило, требующее складской секции, находит и кэшированный маршрут."""
    ctx = await _seed_178(session)
    route = await _import_route(session, ctx)

    section_rows = await load_route_sections(session, [route.id])
    assert [code for _sid, code in section_rows[route.id]] == ROUTE_SECTION_CODES

    payload = {"color": "серебро", "output_kind": "ГП"}
    plain = await select_route_for_payload(session, payload, profile_id=ctx.profile.id)
    cache = await load_route_selection_batch_cache(session, ctx.profile.id)
    cached = await select_route_for_payload(
        session, payload, profile_id=ctx.profile.id, batch_cache=cache
    )

    assert plain.route is not None and plain.route.id == route.id
    assert cached.route is not None and cached.route.id == route.id
    assert plain.route_match_reason == cached.route_match_reason == "selection_rules"
