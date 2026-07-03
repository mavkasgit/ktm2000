from __future__ import annotations

from decimal import Decimal

import pytest
from sqlalchemy import select

from app.models.product import Product, ProductType
from app.models.section import Section
from app.models.spg import SpgSection, SpgStorageKind, StorageProductionGroup
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


def test_wip_not_in_spgs_data():
    """WIP как отдельный SPG удалён — слит с ANOD как wip-секция WIP_WH."""
    codes = {item["code"] for item in SPGS_DATA}
    assert "WIP" not in codes


def test_anod_has_wip_wh_and_storage_kind_wip():
    """ANOD содержит секции ANOD + WIP_WH и имеет storage_kind=wip."""
    anod = next(item for item in SPGS_DATA if item["code"] == "ANOD")
    assert anod["section_codes"] == ["ANOD", "WIP_WH"]
    assert anod.get("storage_kind") == "wip"


@pytest.mark.asyncio
async def test_wip_wh_is_bound_only_to_anod(session):
    """WIP_WH секция должна быть привязана только к ANOD (как склад
    полуфабриката после анодирования)."""
    sections_map = await _seed_default_sections(session)
    await seed_spgs(session, SPGS_DATA, sections_map)
    await session.commit()

    wip_wh = sections_map["WIP_WH"]
    bindings = (
        await session.execute(select(SpgSection).where(SpgSection.section_id == wip_wh.id))
    ).scalars().all()
    assert len(bindings) == 1, (
        "WIP_WH должна быть привязана ровно к одному SPG "
        f"(получили {len(bindings)})"
    )
    spg = await session.get(StorageProductionGroup, bindings[0].spg_id)
    assert spg.code == "ANOD", (
        f"WIP_WH должна быть привязана к ANOD, а не к {spg.code}"
    )


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
async def test_other_spgs_keep_their_sections_after_seed(session):
    """STOCK, PREP, ANOD, PACK и FG должны сохранять свои секции после пересева."""
    sections_map = await _seed_default_sections(session)
    await seed_spgs(session, SPGS_DATA, sections_map)
    await session.commit()

    expectations: list[tuple[str, list[str]]] = [
        ("STOCK", ["WH"]),
        ("PREP", ["DRILL", "PRESS", "SHOT"]),
        ("ANOD", ["ANOD", "WIP_WH"]),
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
async def test_anod_storage_kind_persists_to_db(session):
    """ANOD должен сохранить storage_kind=wip после seed_spgs (через БД)."""
    sections_map = await _seed_default_sections(session)
    await seed_spgs(session, SPGS_DATA, sections_map)
    await session.commit()

    anod = await session.scalar(
        select(StorageProductionGroup).where(StorageProductionGroup.code == "ANOD")
    )
    assert anod is not None
    assert anod.storage_kind == SpgStorageKind.wip
    assert anod.is_active is True
    assert anod.sort_order == 30


@pytest.mark.asyncio
async def test_wip_can_hold_manual_remainder_in_db(session):
    """ANOD (через wip-секцию WIP_WH) может хранить SpgRemainder с пройденными этапами (прямая запись)."""
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

    # Находим ANOD через JOIN по секции WIP_WH (как в demo_production_seeder).
    anod = await session.scalar(
        select(StorageProductionGroup)
        .join(SpgSection, SpgSection.spg_id == StorageProductionGroup.id)
        .join(Section, SpgSection.section_id == Section.id)
        .where(Section.code == "WIP_WH")
    )
    assert anod is not None
    assert anod.code == "ANOD"

    rem = SpgRemainder(
        product_id=product.id,
        spg_id=anod.id,
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
        select(SpgRemainder).where(SpgRemainder.spg_id == anod.id)
    )
    assert found is not None
    assert found.product_id == product.id
    assert found.remainder_quantity == Decimal("33.000")
    assert len(found.completed_stages_json) == 1
    assert found.source == "manual"


@pytest.mark.asyncio
async def test_wip_manual_remainder_via_api(client, session):
    """ANOD (через wip-секцию WIP_WH) доступен через API ручного ввода остатков."""
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

    # Находим ANOD через JOIN по секции WIP_WH.
    anod = await session.scalar(
        select(StorageProductionGroup)
        .join(SpgSection, SpgSection.spg_id == StorageProductionGroup.id)
        .join(Section, SpgSection.section_id == Section.id)
        .where(Section.code == "WIP_WH")
    )
    assert anod is not None
    assert anod.code == "ANOD"

    resp = await client.post(
        f"/api/spg/{anod.id}/remainders",
        json={
            "product_id": product.id,
            "quantity": 17.5,
            "completed_stages": [],
        },
    )
    assert resp.status_code == 201, resp.text
    body = resp.json()
    assert body["spg_code"] == "ANOD"
    assert float(body["remainder_quantity"]) == 17.5

    rem = await session.scalar(
        select(SpgRemainder).where(SpgRemainder.id == body["id"])
    )
    assert rem is not None
    assert rem.spg_id == anod.id


@pytest.mark.asyncio
async def test_list_spgs_includes_anod_with_wip_wh_and_excludes_wip(client, session):
    """GET /api/spg возвращает ANOD с секцией WIP_WH, и WIP как SPG отсутствует в списке."""
    sections_map = await _seed_default_sections(session)
    await seed_spgs(session, SPGS_DATA, sections_map)
    await session.commit()

    resp = await client.get("/api/spg")
    assert resp.status_code == 200
    data = resp.json()

    codes = {item["code"] for item in data}
    assert "WIP" not in codes, "WIP как SPG должен быть удалён из списка"
    assert "ANOD" in codes, "ANOD должен присутствовать"

    anod = next(item for item in data if item["code"] == "ANOD")
    section_codes = {sec["section_code"] for sec in anod["sections"]}
    assert section_codes == {"ANOD", "WIP_WH"}, (
        f"ANOD должен быть привязан к ANOD + WIP_WH, получили {section_codes}"
    )
    assert anod["is_active"] is True
