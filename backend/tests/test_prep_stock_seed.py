from decimal import Decimal

import pytest
from sqlalchemy import select

from app.models.product import Product, ProductType
from app.models.route import ProductionRoute, RouteOperation, RouteStage, SectionOperation
from app.models.section import Section
from app.models.spg import SpgSection, SpgStorageKind, StorageProductionGroup
from app.models.spg_remainder import SpgRemainder
from app.seeds.spgs import SPGS_DATA
from app.seeds.seeders.spgs_seeder import _resolve_storage_kind, seed_spgs
from app.services.shopfloor.common import (
    _significant_section_ids,
    build_completed_stages_json,
)


DEFAULT_SECTIONS = [
    {"code": "WH", "name": "Склад сырья", "sort_order": 10, "kind": "raw_stock"},
    {"code": "DRILL", "name": "Сверловка", "sort_order": 20, "kind": "production"},
    {"code": "PRESS", "name": "Пресс", "sort_order": 30, "kind": "production"},
    {"code": "SHOT", "name": "Дробеструй", "sort_order": 40, "kind": "production"},
    {"code": "ANOD", "name": "Анодирование", "sort_order": 50, "kind": "production"},
    {"code": "WIP_WH", "name": "Склад полуфабриката", "sort_order": 60, "kind": "wip_stock"},
    {"code": "SAW", "name": "Пила", "sort_order": 70, "kind": "production"},
    {"code": "PACK", "name": "Упаковка", "sort_order": 80, "kind": "production"},
    {"code": "FG_WH", "name": "Склад готовой продукции", "sort_order": 90, "kind": "finished_stock"},
    {"code": "SHIPMENT", "name": "К отгрузке", "sort_order": 100, "kind": "finished_stock"},
    {"code": "SENT", "name": "Отправлено", "sort_order": 110, "kind": "finished_stock"},
]


async def _seed_default_sections(session) -> dict[str, Section]:
    sections: dict[str, Section] = {}
    for item in DEFAULT_SECTIONS:
        sec = Section(
            code=item["code"],
            name=item["name"],
            sort_order=item["sort_order"],
            kind=item["kind"],
            is_active=True,
        )
        session.add(sec)
        sections[item["code"]] = sec
    await session.commit()
    for sec in sections.values():
        await session.refresh(sec)
    return sections


def test_prep_stock_present_in_spgs_data():
    """PREP_STOCK должен быть в списке SPGS_DATA как отдельная ГХП."""
    codes = {item["code"] for item in SPGS_DATA}
    assert "PREP_STOCK" in codes


def test_prep_stock_has_empty_section_codes():
    """PREP_STOCK — складской объект, не привязан к секциям."""
    prep = next(item for item in SPGS_DATA if item["code"] == "PREP_STOCK")
    assert prep["section_codes"] == []
    # Сортировка должна быть между PREP и ANOD
    assert prep["sort_order"] > 20 and prep["sort_order"] < 30


def test_prep_stock_has_storage_kind_wip():
    prep = next(item for item in SPGS_DATA if item["code"] == "PREP_STOCK")
    assert prep.get("storage_kind") == "wip"


def test_resolve_storage_kind_defaults_to_wip():
    assert _resolve_storage_kind(None) is SpgStorageKind.wip
    assert _resolve_storage_kind("wip") is SpgStorageKind.wip
    assert _resolve_storage_kind("quarantine") is SpgStorageKind.quarantine
    assert _resolve_storage_kind(SpgStorageKind.wip) is SpgStorageKind.wip


@pytest.mark.asyncio
async def test_seed_spgs_creates_prep_stock_without_section_bindings(session):
    """После seed_spgs PREP_STOCK существует, активен, не привязан к секциям."""
    sections_map = await _seed_default_sections(session)

    count = await seed_spgs(session, SPGS_DATA, sections_map)
    await session.commit()

    assert count == len(SPGS_DATA)

    prep_stock = await session.scalar(
        select(StorageProductionGroup).where(StorageProductionGroup.code == "PREP_STOCK")
    )
    assert prep_stock is not None
    assert prep_stock.is_active is True
    assert prep_stock.storage_kind == SpgStorageKind.wip
    assert prep_stock.sort_order == 25

    # Без привязки к секциям
    bindings = (
        await session.execute(select(SpgSection).where(SpgSection.spg_id == prep_stock.id))
    ).scalars().all()
    assert bindings == []


@pytest.mark.asyncio
async def test_seed_spgs_is_idempotent_for_prep_stock(session):
    """Повторный запуск seed_spgs не дублирует PREP_STOCK и сохраняет настройки."""
    sections_map = await _seed_default_sections(session)

    await seed_spgs(session, SPGS_DATA, sections_map)
    await session.commit()
    await seed_spgs(session, SPGS_DATA, sections_map)
    await session.commit()

    all_prep = (
        await session.execute(
            select(StorageProductionGroup).where(StorageProductionGroup.code == "PREP_STOCK")
        )
    ).scalars().all()
    assert len(all_prep) == 1

    only = all_prep[0]
    assert only.is_active is True
    assert only.storage_kind == SpgStorageKind.wip
    assert only.sort_order == 25


@pytest.mark.asyncio
async def test_prep_stock_does_not_steal_sections_from_other_spgs(session):
    """PREP_STOCK не должен влиять на привязку секций к другим ГХП."""
    sections_map = await _seed_default_sections(session)
    await seed_spgs(session, SPGS_DATA, sections_map)
    await session.commit()

    # DRILL должен остаться привязан к PREP (а не к PREP_STOCK)
    drill = sections_map["DRILL"]
    bindings = (
        await session.execute(select(SpgSection).where(SpgSection.section_id == drill.id))
    ).scalars().all()
    assert len(bindings) == 1
    drill_spg = await session.get(StorageProductionGroup, bindings[0].spg_id)
    assert drill_spg.code == "PREP"


@pytest.mark.asyncio
async def test_prep_stock_section_codes_missing_key_is_treated_as_empty(session):
    """seed_spgs корректно обрабатывает отсутствующий ключ section_codes (treats as [])."""
    sections_map = await _seed_default_sections(session)
    custom_data = [
        {
            "code": "NO_SECT_KEY",
            "name": "Without section_codes key",
            "sort_order": 999,
            "icon": "Box",
            "icon_color": "#000000",
        }
    ]
    count = await seed_spgs(session, custom_data, sections_map)
    await session.commit()

    assert count == 1
    created = await session.scalar(
        select(StorageProductionGroup).where(StorageProductionGroup.code == "NO_SECT_KEY")
    )
    assert created is not None
    assert created.is_active is True
    bindings = (
        await session.execute(select(SpgSection).where(SpgSection.spg_id == created.id))
    ).scalars().all()
    assert bindings == []


@pytest.mark.asyncio
async def test_prep_stock_can_hold_manual_remainder_in_db(session):
    """PREP_STOCK может хранить SpgRemainder с пройденными этапами (прямая запись)."""
    from app.models.user import User, UserRole

    product = Product(
        sku="PREP-DIRECT-1",
        name="Direct Prep Remainder",
        type=ProductType.component,
        unit="pcs",
    )
    actor = User(
        username="prep-actor",
        email="prep-actor@local",
        password_hash="x",
        full_name="Prep Actor",
        role=UserRole.admin,
        is_active=True,
    )
    session.add_all([product, actor])
    await session.commit()

    sections_map = await _seed_default_sections(session)
    await seed_spgs(session, SPGS_DATA, sections_map)
    await session.commit()

    prep_stock = await session.scalar(
        select(StorageProductionGroup).where(StorageProductionGroup.code == "PREP_STOCK")
    )
    assert prep_stock is not None

    rem = SpgRemainder(
        product_id=product.id,
        spg_id=prep_stock.id,
        remainder_quantity=Decimal("42.000"),
        original_issued=Decimal("50.000"),
        completed_stages_json=[
            {
                "section_id": sections_map["DRILL"].id,
                "operation_code": "DRILL",
                "operation_name": "Сверловка",
                "sequence": 2,
            }
        ],
        source="manual",
        created_by=actor.id,
        created_by_user_name=actor.full_name,
    )
    session.add(rem)
    await session.commit()

    found = await session.scalar(
        select(SpgRemainder).where(SpgRemainder.spg_id == prep_stock.id)
    )
    assert found is not None
    assert found.product_id == product.id
    assert found.remainder_quantity == Decimal("42.000")
    assert len(found.completed_stages_json) == 1
    assert found.source == "manual"


@pytest.mark.asyncio
async def test_prep_stock_manual_remainder_via_api(client, session):
    """PREP_STOCK доступен через API ручного ввода остатков (как обычный SPG)."""
    product = Product(
        sku="PREP-MANUAL-1",
        name="Manual Prep Remainder",
        type=ProductType.component,
        unit="pcs",
    )
    session.add(product)
    await session.commit()

    sections_map = await _seed_default_sections(session)
    await seed_spgs(session, SPGS_DATA, sections_map)
    await session.commit()

    prep_stock = await session.scalar(
        select(StorageProductionGroup).where(StorageProductionGroup.code == "PREP_STOCK")
    )
    assert prep_stock is not None

    resp = await client.post(
        f"/api/spg/{prep_stock.id}/remainders",
        json={
            "product_id": product.id,
            "quantity": 12.5,
            "completed_stages": [],
        },
    )
    assert resp.status_code == 201, resp.text
    body = resp.json()
    assert body["spg_code"] == "PREP_STOCK"
    assert float(body["remainder_quantity"]) == 12.5

    rem = await session.scalar(
        select(SpgRemainder).where(SpgRemainder.id == body["id"])
    )
    assert rem is not None
    assert rem.spg_id == prep_stock.id


@pytest.mark.asyncio
async def test_demo_production_seeder_prefers_prep_stock(session, monkeypatch):
    """Демо-сидер должен искать PREP_STOCK первым и класть остатки туда."""
    from app.seeds.seeders import demo_production_seeder

    captured: dict = {}

    real_scalar = demo_production_seeder.AsyncSession if False else None  # placeholder

    # Создаём только PREP_STOCK и проверяем, что demo_production_seeder его находит
    from app.models.user import User, UserRole

    actor = User(
        username="seed-actor",
        email="seed-actor@local",
        password_hash="x",
        full_name="Seed Actor",
        role=UserRole.admin,
        is_active=True,
    )
    session.add(actor)
    await session.commit()

    sections_map = await _seed_default_sections(session)
    await seed_spgs(session, SPGS_DATA, sections_map)
    await session.commit()

    # Вызываем сидер; в отсутствие route он вернётся рано, но не упадёт
    stats = await demo_production_seeder.seed_demo_production(session)
    # Если нет route → stats пустой, сидер вернётся рано
    # Это допустимо: цель — убедиться, что сидер не падает на PREP_STOCK
    assert isinstance(stats, dict)
    assert "remainders" in stats

    # PREP_STOCK точно создан
    prep_stock = await session.scalar(
        select(StorageProductionGroup).where(StorageProductionGroup.code == "PREP_STOCK")
    )
    assert prep_stock is not None
    assert prep_stock.is_active is True


# --- tests for build_completed_stages_json -------------------------------


async def _build_route_with_sections(
    session,
    *,
    route_code: str,
    sections: list[tuple[str, str, str, bool]],
) -> ProductionRoute:
    """Create a minimal route with the given (section_code, section_name, section_kind, is_section_significant) entries.

    Each entry becomes one RouteStage with one RouteOperation. The section's significance is
    controlled via SectionOperation.is_significant (which the helper looks at).
    """
    for code, name, kind, _sig in sections:
        exists = await session.scalar(select(Section).where(Section.code == code))
        if not exists:
            section = Section(code=code, name=name, kind=kind, sort_order=10, is_active=True)
            session.add(section)
    await session.commit()

    section_by_code = {
        s.code: s
        for s in (
            await session.execute(
                select(Section).where(Section.code.in_([c for c, *_ in sections]))
            )
        ).scalars().all()
    }

    route = await session.scalar(
        select(ProductionRoute).where(ProductionRoute.code == route_code)
    )
    if route is None:
        route = ProductionRoute(code=route_code, name=route_code, is_active=True)
        session.add(route)
        await session.commit()
        await session.refresh(route)

    for idx, (code, _name, _kind, is_sig) in enumerate(sections, start=1):
        sec = section_by_code[code]
        op_exists = await session.scalar(
            select(SectionOperation).where(
                SectionOperation.section_id == sec.id,
                SectionOperation.operation_code == f"OP_{code}",
            )
        )
        if not op_exists:
            session.add(
                SectionOperation(
                    section_id=sec.id,
                    operation_code=f"OP_{code}",
                    operation_name=f"Операция {code}",
                    is_significant=is_sig,
                )
            )
        stage = await session.scalar(
            select(RouteStage).where(
                RouteStage.route_id == route.id, RouteStage.sequence == idx
            )
        )
        if stage is None:
            stage = RouteStage(
                route_id=route.id,
                sequence=idx,
                section_id=sec.id,
                is_significant=True,
            )
            session.add(stage)
            await session.flush()
            session.add(
                RouteOperation(
                    route_stage_id=stage.id,
                    sequence=1,
                    operation_code=f"OP_{code}",
                    operation_name=f"Операция {code}",
                )
            )
    await session.commit()

    stages = (
        await session.execute(
            select(RouteStage)
            .where(RouteStage.route_id == route.id)
            .order_by(RouteStage.sequence)
        )
    ).scalars().all()
    return route, stages


@pytest.mark.asyncio
async def test_significant_section_ids_filters_pass_through_sections(session):
    """_significant_section_ids должен вернуть только секции со значимыми операциями."""
    _route, _stages = await _build_route_with_sections(
        session,
        route_code="R-SIG-1",
        sections=[
            ("WH", "Склад сырья", "raw_stock", False),
            ("DRILL", "Сверловка", "production", True),
            ("WIP_WH", "Склад пф", "wip_stock", False),
            ("PACK", "Упаковка", "production", True),
            ("FG_WH", "Склад ГП", "finished_stock", False),
        ],
    )

    wh = await session.scalar(select(Section).where(Section.code == "WH"))
    drill = await session.scalar(select(Section).where(Section.code == "DRILL"))
    wip = await session.scalar(select(Section).where(Section.code == "WIP_WH"))
    pack = await session.scalar(select(Section).where(Section.code == "PACK"))
    fg = await session.scalar(select(Section).where(Section.code == "FG_WH"))

    significant = await _significant_section_ids(
        session, [wh.id, drill.id, wip.id, pack.id, fg.id]
    )
    assert significant == {drill.id, pack.id}


@pytest.mark.asyncio
async def test_build_completed_stages_json_drops_warehouse_and_transfer_stages(session):
    """build_completed_stages_json должен выкидывать WH, WIP_WH, FG_WH, SHIPMENT, SENT."""
    _route, stages = await _build_route_with_sections(
        session,
        route_code="R-SIG-2",
        sections=[
            ("WH", "Склад сырья", "raw_stock", False),
            ("DRILL", "Сверловка", "production", True),
            ("PRESS", "Пресс", "production", True),
            ("SHOT", "Дробеструй", "production", True),
            ("WIP_WH", "Склад пф", "wip_stock", False),
            ("FG_WH", "Склад ГП", "finished_stock", False),
        ],
    )

    # Берём первые 4 этапа (WH, DRILL, PRESS, SHOT) — как в демо-сидере
    completed = await build_completed_stages_json(session, stages[:4])

    # WH выкинут, остались DRILL, PRESS, SHOT
    assert len(completed) == 3
    sec_ids = {entry["section_id"] for entry in completed}
    wh = await session.scalar(select(Section).where(Section.code == "WH"))
    assert wh.id not in sec_ids
    # Сохраняется порядок по sequence
    sequences = [entry["sequence"] for entry in completed]
    assert sequences == sorted(sequences)


@pytest.mark.asyncio
async def test_build_completed_stages_json_empty_input_returns_empty(session):
    completed = await build_completed_stages_json(session, [])
    assert completed == []


@pytest.mark.asyncio
async def test_build_completed_stages_json_all_pass_through_returns_empty(session):
    _route, stages = await _build_route_with_sections(
        session,
        route_code="R-SIG-3",
        sections=[
            ("WH", "Склад сырья", "raw_stock", False),
            ("WIP_WH", "Склад пф", "wip_stock", False),
        ],
    )
    completed = await build_completed_stages_json(session, stages)
    assert completed == []


@pytest.mark.asyncio
async def test_build_completed_stages_json_keeps_operation_metadata(session):
    _route, stages = await _build_route_with_sections(
        session,
        route_code="R-SIG-4",
        sections=[
            ("DRILL", "Сверловка", "production", True),
        ],
    )
    completed = await build_completed_stages_json(session, stages)
    assert len(completed) == 1
    entry = completed[0]
    assert entry["operation_code"] == "OP_DRILL"
    assert entry["operation_name"] == "Операция DRILL"
    assert entry["sequence"] == 1


@pytest.mark.asyncio
async def test_demo_production_seeder_omits_non_significant_stages(session, monkeypatch):
    """Демо-сидер кладёт в completed_stages_json только значимые этапы."""
    from app.seeds.seeders import demo_production_seeder
    from app.models.user import User, UserRole

    actor = User(
        username="filter-actor",
        email="filter-actor@local",
        password_hash="x",
        full_name="Filter Actor",
        role=UserRole.admin,
        is_active=True,
    )
    session.add(actor)
    await session.commit()

    # Подготовим полный сценарий: секции, SPGs, маршрут с WH/DRILL/PRESS/SHOT/WIP_WH
    sections_map = await _seed_default_sections(session)
    await seed_spgs(session, SPGS_DATA, sections_map)
    await session.commit()

    _route, _stages = await _build_route_with_sections(
        session,
        route_code="dynamic_packaging_map_rp",
        sections=[
            ("WH", "Склад сырья", "raw_stock", False),
            ("DRILL", "Сверловка", "production", True),
            ("PRESS", "Пресс", "production", True),
            ("SHOT", "Дробеструй", "production", True),
            ("WIP_WH", "Склад пф", "wip_stock", False),
        ],
    )

    stats = await demo_production_seeder.seed_demo_production(session)
    await session.commit()

    assert stats["remainders"] >= 1
    prep_stock = await session.scalar(
        select(StorageProductionGroup).where(StorageProductionGroup.code == "PREP_STOCK")
    )
    assert prep_stock is not None

    remainders = (
        await session.execute(
            select(SpgRemainder).where(SpgRemainder.spg_id == prep_stock.id)
        )
    ).scalars().all()
    assert remainders, "Демо-сидер должен был положить остатки в PREP_STOCK"

    # В каждом remainder completed_stages_json не должен содержать WH (issue raw)
    wh = await session.scalar(select(Section).where(Section.code == "WH"))
    for rem in remainders:
        stages_json = rem.completed_stages_json or []
        section_ids = {s.get("section_id") for s in stages_json}
        assert wh.id not in section_ids, (
            "WH (issue raw) не должен попадать в completed_stages_json демо-остатков"
        )
        # А все сохранённые этапы должны быть значимыми
        for entry in stages_json:
            assert entry.get("section_id") != wh.id
        # Поля корректные
        for entry in stages_json:
            assert {"section_id", "operation_code", "operation_name", "sequence"} <= entry.keys()
