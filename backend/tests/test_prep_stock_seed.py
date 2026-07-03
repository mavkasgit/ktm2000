from __future__ import annotations

from decimal import Decimal

import pytest
from sqlalchemy import select

from app.models.product import Product, ProductType
from app.models.route import (
    ProductionRoute,
    RouteOperation,
    RouteStage,
    SectionOperation,
)
from app.models.section import Section
from app.models.spg import SpgSection, SpgStorageKind, StorageProductionGroup
from app.seeds.spgs import SPGS_DATA
from app.seeds.seeders.spgs_seeder import _resolve_storage_kind, seed_spgs
from app.services.route_storage_classifier import (
    STAGE_KIND_PRODUCTION,
    STAGE_KIND_TRANSIT,
    is_storage_section,
)
from app.services.shopfloor.common import build_completed_stages_json


DEFAULT_SECTIONS = [
    {"code": "WH", "name": "Склад сырья", "sort_order": 10, "kind": "raw_stock"},
    {"code": "DRILL", "name": "Сверловка", "sort_order": 20, "kind": "production"},
    {"code": "PRESS", "name": "Пресс", "sort_order": 30, "kind": "production"},
    {"code": "SHOT", "name": "Дробеструй", "sort_order": 40, "kind": "production"},
    {"code": "PREP_STOCK", "name": "Склад подготовки", "sort_order": 45, "kind": "wip_stock"},
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


def test_prep_present_in_spgs_data():
    """PREP должен быть в списке SPGS_DATA."""
    codes = {item["code"] for item in SPGS_DATA}
    assert "PREP" in codes


def test_prep_stock_section_in_default_sections():
    """PREP_STOCK — wip-секция (kind=wip_stock), не SPG."""
    sec = next(item for item in DEFAULT_SECTIONS if item["code"] == "PREP_STOCK")
    assert sec["kind"] == "wip_stock"


def test_prep_stock_not_in_spgs_data():
    """PREP_STOCK как SPG удалён — теперь это секция внутри PREP."""
    codes = {item["code"] for item in SPGS_DATA}
    assert "PREP_STOCK" not in codes


def test_prep_has_all_prep_sections():
    """PREP содержит 3 production + 1 storage секцию."""
    prep = next(item for item in SPGS_DATA if item["code"] == "PREP")
    assert prep["section_codes"] == ["DRILL", "PRESS", "SHOT", "PREP_STOCK"]


def test_prep_has_storage_kind_wip():
    """PREP имеет storage_kind=wip (включая складскую секцию PREP_STOCK)."""
    prep = next(item for item in SPGS_DATA if item["code"] == "PREP")
    assert prep.get("storage_kind") == "wip"


def test_resolve_storage_kind_defaults_to_wip():
    assert _resolve_storage_kind(None) is SpgStorageKind.wip
    assert _resolve_storage_kind("wip") is SpgStorageKind.wip
    assert _resolve_storage_kind("quarantine") is SpgStorageKind.quarantine
    assert _resolve_storage_kind(SpgStorageKind.wip) is SpgStorageKind.wip


@pytest.mark.asyncio
async def test_seed_spgs_creates_prep_with_all_sections_and_storage(session):
    """После seed_spgs PREP существует, привязан к 4 секциям (3 production + 1 storage),
    storage_kind=wip."""
    sections_map = await _seed_default_sections(session)

    count = await seed_spgs(session, SPGS_DATA, sections_map)
    await session.commit()

    assert count == len(SPGS_DATA)

    prep = await session.scalar(
        select(StorageProductionGroup).where(StorageProductionGroup.code == "PREP")
    )
    assert prep is not None
    assert prep.is_active is True
    assert prep.storage_kind == SpgStorageKind.wip
    assert prep.sort_order == 20

    bindings = (
        await session.execute(select(SpgSection).where(SpgSection.spg_id == prep.id))
    ).scalars().all()
    assert len(bindings) == 4
    bound_section_codes = {sections_map[code].id for code in ("DRILL", "PRESS", "SHOT", "PREP_STOCK")}
    assert {b.section_id for b in bindings} == bound_section_codes


@pytest.mark.asyncio
async def test_seed_spgs_is_idempotent_for_prep(session):
    """Повторный запуск seed_spgs не дублирует PREP и сохраняет настройки."""
    sections_map = await _seed_default_sections(session)

    await seed_spgs(session, SPGS_DATA, sections_map)
    await session.commit()
    await seed_spgs(session, SPGS_DATA, sections_map)
    await session.commit()

    all_prep = (
        await session.execute(
            select(StorageProductionGroup).where(StorageProductionGroup.code == "PREP")
        )
    ).scalars().all()
    assert len(all_prep) == 1

    only = all_prep[0]
    assert only.is_active is True
    assert only.storage_kind == SpgStorageKind.wip
    assert only.sort_order == 20

    bindings = (
        await session.execute(select(SpgSection).where(SpgSection.spg_id == only.id))
    ).scalars().all()
    assert len(bindings) == 4


@pytest.mark.asyncio
async def test_prep_binds_only_prep_sections(session):
    """PREP не должен привязывать секции других ГХП (ANOD, FG, и т.д.)."""
    sections_map = await _seed_default_sections(session)
    await seed_spgs(session, SPGS_DATA, sections_map)
    await session.commit()

    for code in ("DRILL", "PRESS", "SHOT", "PREP_STOCK"):
        sec = sections_map[code]
        bindings = (
            await session.execute(select(SpgSection).where(SpgSection.section_id == sec.id))
        ).scalars().all()
        assert len(bindings) == 1
        bound_spg = await session.get(StorageProductionGroup, bindings[0].spg_id)
        assert bound_spg.code == "PREP"


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
async def test_prep_can_hold_manual_remainder_in_db(session):
    """PREP (с PREP_STOCK секцией) может хранить SpgRemainder с пройденными этапами (прямая запись)."""
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

    prep = await session.scalar(
        select(StorageProductionGroup).where(StorageProductionGroup.code == "PREP")
    )
    assert prep is not None

    rem = SpgRemainder(
        product_id=product.id,
        spg_id=prep.id,
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
        select(SpgRemainder).where(SpgRemainder.spg_id == prep.id)
    )
    assert found is not None
    assert found.product_id == product.id
    assert found.remainder_quantity == Decimal("42.000")
    assert len(found.completed_stages_json) == 1
    assert found.source == "manual"


@pytest.mark.asyncio
async def test_prep_manual_remainder_via_api(client, session):
    """PREP доступен через API ручного ввода остатков (как обычный SPG)."""
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

    prep = await session.scalar(
        select(StorageProductionGroup).where(StorageProductionGroup.code == "PREP")
    )
    assert prep is not None

    resp = await client.post(
        f"/api/spg/{prep.id}/remainders",
        json={
            "product_id": product.id,
            "quantity": 12.5,
            "completed_stages": [],
        },
    )
    assert resp.status_code == 201, resp.text
    body = resp.json()
    assert body["spg_code"] == "PREP"
    assert float(body["remainder_quantity"]) == 12.5

    rem = await session.scalar(
        select(SpgRemainder).where(SpgRemainder.id == body["id"])
    )
    assert rem is not None
    assert rem.spg_id == prep.id


@pytest.mark.asyncio
async def test_demo_production_seeder_finds_prep_via_section(session, monkeypatch):
    """Демо-сидер должен находить PREP через секцию PREP_STOCK и класть остатки туда."""
    from app.seeds.seeders import demo_production_seeder
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
    assert isinstance(stats, dict)
    assert "remainders" in stats

    # PREP точно создан и содержит PREP_STOCK
    prep = await session.scalar(
        select(StorageProductionGroup).where(StorageProductionGroup.code == "PREP")
    )
    assert prep is not None
    assert prep.is_active is True
    assert prep.storage_kind == SpgStorageKind.wip
    prep_stock_sec = sections_map["PREP_STOCK"]
    bindings = (
        await session.execute(
            select(SpgSection).where(
                SpgSection.spg_id == prep.id,
                SpgSection.section_id == prep_stock_sec.id,
            )
        )
    ).scalars().all()
    assert len(bindings) == 1


# --- tests for build_completed_stages_json -------------------------------


async def _build_route_with_sections(
    session,
    *,
    route_code: str,
    sections: list[tuple[str, str, str, bool]],
) -> ProductionRoute:
    """Create a minimal route with the given (section_code, section_name, section_kind, is_section_significant) entries.

    Each entry becomes one RouteStage with one RouteOperation.

    Section kind drives ``stage_kind``: production sections → ``production`` stage,
    storage sections (``raw_stock``/``wip_stock``/``finished_stock``) → ``transit``
    stage with ``storage_section_id`` set and ``section_id`` NULL.  The
    ``is_section_significant`` flag is now stored on ``SectionOperation.operation_type``
    (``'production'`` or ``'transport'``).
    """
    from app.services.route_storage_classifier import is_storage_section

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
        op_type = (
            "transport" if (not is_sig or is_storage_section(sec)) else "production"
        )
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
                    operation_type=op_type,
                )
            )
        stage = await session.scalar(
            select(RouteStage).where(
                RouteStage.route_id == route.id, RouteStage.sequence == idx
            )
        )
        if stage is None:
            if is_storage_section(sec):
                stage = RouteStage(
                    route_id=route.id,
                    sequence=idx,
                    section_id=None,
                    stage_kind=STAGE_KIND_TRANSIT,
                    storage_section_id=sec.id,
                )
            else:
                stage = RouteStage(
                    route_id=route.id,
                    sequence=idx,
                    section_id=sec.id,
                    stage_kind=STAGE_KIND_PRODUCTION,
                )
            session.add(stage)
            await session.flush()
            if not is_storage_section(sec):
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
    """``is_storage_section`` correctly identifies storage sections so they can be
    treated as transit by the new ``stage_kind`` model."""
    sections = [
        ("WH", "Склад сырья", "raw_stock"),
        ("DRILL", "Сверловка", "production"),
        ("WIP_WH", "Склад пф", "wip_stock"),
        ("PACK", "Упаковка", "production"),
        ("FG_WH", "Склад ГП", "finished_stock"),
    ]
    for code, name, kind in sections:
        section = await session.scalar(select(Section).where(Section.code == code))
        if section is None:
            section = Section(code=code, name=name, kind=kind, is_active=True, sort_order=0)
            session.add(section)
    await session.flush()

    wh = await session.scalar(select(Section).where(Section.code == "WH"))
    drill = await session.scalar(select(Section).where(Section.code == "DRILL"))
    wip = await session.scalar(select(Section).where(Section.code == "WIP_WH"))
    pack = await session.scalar(select(Section).where(Section.code == "PACK"))
    fg = await session.scalar(select(Section).where(Section.code == "FG_WH"))

    # Production sections are NOT storage, storage sections ARE storage.
    assert is_storage_section(wh) is True
    assert is_storage_section(drill) is False
    assert is_storage_section(wip) is True
    assert is_storage_section(pack) is False
    assert is_storage_section(fg) is True


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
    prep = await session.scalar(
        select(StorageProductionGroup).where(StorageProductionGroup.code == "PREP")
    )
    assert prep is not None

    remainders = (
        await session.execute(
            select(SpgRemainder).where(SpgRemainder.spg_id == prep.id)
        )
    ).scalars().all()
    assert remainders, "Демо-сидер должен был положить остатки в PREP"

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
