from __future__ import annotations

from decimal import Decimal

import pytest
from sqlalchemy import select

from app.models.product import Product, ProductType
from app.models.section import Section
from app.models.spg import SpgSection, SpgStorageKind, StorageProductionGroup
from app.models.spg_remainder import SpgRemainder
from app.seeds.spgs import SPGS_DATA
from app.seeds.seeders.spgs_seeder import seed_spgs
from app.models.user import User, UserRole


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


def test_wip_present_in_spgs_data():
    """WIP должен быть в списке SPGS_DATA."""
    codes = {item["code"] for item in SPGS_DATA}
    assert "WIP" in codes


def test_wip_has_empty_section_codes():
    """WIP — складской объект, не привязан к секциям (sectionless)."""
    wip = next(item for item in SPGS_DATA if item["code"] == "WIP")
    assert wip["section_codes"] == []
    assert wip["sort_order"] == 40


def test_wip_has_storage_kind_wip():
    """WIP имеет явный storage_kind=wip."""
    wip = next(item for item in SPGS_DATA if item["code"] == "WIP")
    assert wip.get("storage_kind") == "wip"


@pytest.mark.asyncio
async def test_seed_spgs_creates_wip_without_section_bindings(session):
    """После seed_spgs WIP существует, активен, не привязан к секциям."""
    sections_map = await _seed_default_sections(session)
    await seed_spgs(session, SPGS_DATA, sections_map)
    await session.commit()

    wip = await session.scalar(
        select(StorageProductionGroup).where(StorageProductionGroup.code == "WIP")
    )
    assert wip is not None
    assert wip.is_active is True
    assert wip.storage_kind == SpgStorageKind.wip
    assert wip.sort_order == 40

    bindings = (
        await session.execute(select(SpgSection).where(SpgSection.spg_id == wip.id))
    ).scalars().all()
    assert bindings == []


@pytest.mark.asyncio
async def test_seed_spgs_is_idempotent_for_wip(session):
    """Повторный запуск seed_spgs не дублирует WIP и сохраняет настройки."""
    sections_map = await _seed_default_sections(session)
    await seed_spgs(session, SPGS_DATA, sections_map)
    await session.commit()
    await seed_spgs(session, SPGS_DATA, sections_map)
    await session.commit()

    all_wip = (
        await session.execute(
            select(StorageProductionGroup).where(StorageProductionGroup.code == "WIP")
        )
    ).scalars().all()
    assert len(all_wip) == 1

    only = all_wip[0]
    assert only.is_active is True
    assert only.storage_kind == SpgStorageKind.wip
    assert only.sort_order == 40
    assert only.icon == "Layers"


@pytest.mark.asyncio
async def test_wip_does_not_steal_wip_wh_section_from_other_spgs(session):
    """WIP SPG не должен быть привязан к WIP_WH (и секция WIP_WH не должна
    оказаться привязанной к другому ГХП после пересева)."""
    sections_map = await _seed_default_sections(session)
    await seed_spgs(session, SPGS_DATA, sections_map)
    await session.commit()

    wip_wh = sections_map["WIP_WH"]
    bindings = (
        await session.execute(select(SpgSection).where(SpgSection.section_id == wip_wh.id))
    ).scalars().all()
    assert bindings == [], "WIP_WH секция не должна быть привязана ни к какому ГХП после пересева"


@pytest.mark.asyncio
async def test_wip_wh_section_still_exists_after_seed(session):
    """Секция WIP_WH должна по-прежнему существовать в БД после пересева
    (она нужна для маршрутов и selection rules)."""
    sections_map = await _seed_default_sections(session)
    await seed_spgs(session, SPGS_DATA, sections_map)
    await session.commit()

    wip_wh = await session.scalar(select(Section).where(Section.code == "WIP_WH"))
    assert wip_wh is not None
    assert wip_wh.is_active is True
    assert wip_wh.kind == "wip_stock"


@pytest.mark.asyncio
async def test_other_spgs_keep_their_sections_after_wip_decoupling(session):
    """PREP, ANOD, PACK, FG и STOCK не должны потерять свои секции после того,
    как WIP стал sectionless."""
    sections_map = await _seed_default_sections(session)
    await seed_spgs(session, SPGS_DATA, sections_map)
    await session.commit()

    expectations: list[tuple[str, list[str]]] = [
        ("STOCK", ["WH"]),
        ("PREP", ["DRILL", "PRESS", "SHOT"]),
        ("ANOD", ["ANOD"]),
        ("PACK", ["SAW", "PACK"]),
        ("FG", ["FG_WH", "SHIPMENT", "SENT"]),
    ]
    for spg_code, expected_section_codes in expectations:
        spg = await session.scalar(
            select(StorageProductionGroup).where(StorageProductionGroup.code == spg_code)
        )
        assert spg is not None, f"{spg_code} должен быть засеян"
        bindings = (
            await session.execute(select(SpgSection).where(SpgSection.spg_id == spg.id))
        ).scalars().all()
        bound_section_ids = {b.section_id for b in bindings}
        expected_section_ids = {sections_map[code].id for code in expected_section_codes}
        assert bound_section_ids == expected_section_ids, (
            f"{spg_code} должен быть привязан к {expected_section_codes}, "
            f"получили {[s.code for s in sections_map.values() if s.id in bound_section_ids]}"
        )


@pytest.mark.asyncio
async def test_wip_can_hold_manual_remainder_in_db(session):
    """WIP может хранить SpgRemainder с пройденными этапами (прямая запись)."""
    from app.models.user import User, UserRole

    product = Product(
        sku="WIP-DIRECT-1",
        name="Direct WIP Remainder",
        type=ProductType.component,
        unit="pcs",
    )
    actor = User(
        username="wip-actor",
        email="wip-actor@local",
        password_hash="x",
        full_name="WIP Actor",
        role=UserRole.admin,
        is_active=True,
    )
    session.add_all([product, actor])
    await session.commit()

    sections_map = await _seed_default_sections(session)
    await seed_spgs(session, SPGS_DATA, sections_map)
    await session.commit()

    wip = await session.scalar(
        select(StorageProductionGroup).where(StorageProductionGroup.code == "WIP")
    )
    assert wip is not None

    rem = SpgRemainder(
        product_id=product.id,
        spg_id=wip.id,
        remainder_quantity=Decimal("33.000"),
        original_issued=Decimal("40.000"),
        completed_stages_json=[
            {
                "section_id": sections_map["ANOD"].id,
                "operation_code": "ANOD_01",
                "operation_name": "Серебро",
                "sequence": 5,
            }
        ],
        source="manual",
        created_by=actor.id,
        created_by_user_name=actor.full_name,
    )
    session.add(rem)
    await session.commit()

    found = await session.scalar(
        select(SpgRemainder).where(SpgRemainder.spg_id == wip.id)
    )
    assert found is not None
    assert found.product_id == product.id
    assert found.remainder_quantity == Decimal("33.000")
    assert len(found.completed_stages_json) == 1
    assert found.source == "manual"


@pytest.mark.asyncio
async def test_wip_manual_remainder_via_api(client, session):
    """WIP доступен через API ручного ввода остатков (как обычный SPG)."""
    product = Product(
        sku="WIP-MANUAL-1",
        name="Manual WIP Remainder",
        type=ProductType.component,
        unit="pcs",
    )
    session.add(product)
    await session.commit()

    sections_map = await _seed_default_sections(session)
    await seed_spgs(session, SPGS_DATA, sections_map)
    await session.commit()

    wip = await session.scalar(
        select(StorageProductionGroup).where(StorageProductionGroup.code == "WIP")
    )
    assert wip is not None

    resp = await client.post(
        f"/api/spg/{wip.id}/remainders",
        json={
            "product_id": product.id,
            "quantity": 17.5,
            "completed_stages": [],
        },
    )
    assert resp.status_code == 201, resp.text
    body = resp.json()
    assert body["spg_code"] == "WIP"
    assert float(body["remainder_quantity"]) == 17.5

    rem = await session.scalar(
        select(SpgRemainder).where(SpgRemainder.id == body["id"])
    )
    assert rem is not None
    assert rem.spg_id == wip.id


@pytest.mark.asyncio
async def test_list_spgs_includes_wip_with_empty_sections(client, session):
    """GET /api/spg возвращает WIP с пустым списком секций."""
    sections_map = await _seed_default_sections(session)
    await seed_spgs(session, SPGS_DATA, sections_map)
    await session.commit()

    resp = await client.get("/api/spg")
    assert resp.status_code == 200
    data = resp.json()
    wip = next(item for item in data if item["code"] == "WIP")
    assert wip["sections"] == []
    assert wip["is_active"] is True
