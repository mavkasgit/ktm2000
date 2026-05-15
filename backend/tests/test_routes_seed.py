import pytest
from sqlalchemy import select

from app.models.route import RouteSelectionRule
from app.models.section import Section
from app.services.route_selection import select_route_for_payload


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


@pytest.mark.asyncio
async def test_seed_routes_creates_characteristic_routes(client, session) -> None:
    for item in DEFAULT_SECTIONS:
        session.add(Section(code=item["code"], name=item["name"], sort_order=item["sort_order"], kind=item["kind"], is_active=True))
    await session.commit()

    response = await client.post("/api/routes-seed")
    assert response.status_code == 201
    data = response.json()
    assert len(data) == 12
    names = [route["name"] for route in data]
    assert "ГП • Сверло • С дробеструем" in names
    assert "ГП • Без первичной • Без дробеструя" in names
    assert "П/ф • Пресс • С дробеструем" in names
    assert "П/ф • Без первичной • Без дробеструя" in names
    first_rules_count = len((await session.execute(select(RouteSelectionRule))).scalars().all())
    assert first_rules_count == 9

    # idempotency/update behavior
    response2 = await client.post("/api/routes-seed")
    assert response2.status_code == 201
    data2 = response2.json()
    assert len(data2) == 12
    second_rules = (await session.execute(select(RouteSelectionRule))).scalars().all()
    assert len(second_rules) == first_rules_count
    unique_keys = {rule.code for rule in second_rules}
    assert len(unique_keys) == first_rules_count


@pytest.mark.asyncio
async def test_route_selection_rule_can_be_updated(client, session) -> None:
    for item in DEFAULT_SECTIONS:
        session.add(Section(code=item["code"], name=item["name"], sort_order=item["sort_order"], kind=item["kind"], is_active=True))
    await session.commit()

    response = await client.post("/api/routes-seed")
    assert response.status_code == 201
    rules_response = await client.get("/api/route-selection-rules")
    assert rules_response.status_code == 200
    rule = rules_response.json()[0]
    drill = await session.scalar(select(Section).where(Section.code == "DRILL"))

    update_response = await client.put(
        f"/api/route-selection-rules/{rule['id']}",
        json={
            "code": rule["code"],
            "name": "Updated rule",
            "priority": 321,
            "is_active": False,
            "conditions": [{"source": "payload", "field_path": "operation", "operator": "contains", "value": "сверл", "case_sensitive": False}],
            "actions": [{"action": "require_section", "section_id": drill.id}],
        },
    )

    assert update_response.status_code == 200
    data = update_response.json()
    assert data["name"] == "Updated rule"
    assert data["priority"] == 321
    assert data["is_active"] is False
    assert data["conditions"][0]["field_path"] == "operation"


@pytest.mark.asyncio
async def test_seeded_rules_select_drill_finished_good_route(client, session) -> None:
    for item in DEFAULT_SECTIONS:
        session.add(Section(code=item["code"], name=item["name"], sort_order=item["sort_order"], kind=item["kind"], is_active=True))
    await session.commit()

    response = await client.post("/api/routes-seed")
    assert response.status_code == 201

    result = await select_route_for_payload(
        session,
        {"operation": "сверловка", "output_kind": "finished_good", "additional_pack_operations": []},
    )

    assert result.route is not None
    assert result.route.name == "ГП • Сверло • С дробеструем"
    selected = next(candidate for candidate in result.candidate_routes if candidate.route_id == result.route.id)
    assert "DRILL" in selected.section_codes
    assert "WIP_WH" in selected.section_codes
    assert "SAW" in selected.section_codes
    assert "PACK" in selected.section_codes


@pytest.mark.asyncio
async def test_seeded_rules_exclude_finished_good_branch_for_semi_finished(client, session) -> None:
    for item in DEFAULT_SECTIONS:
        session.add(Section(code=item["code"], name=item["name"], sort_order=item["sort_order"], kind=item["kind"], is_active=True))
    await session.commit()

    response = await client.post("/api/routes-seed")
    assert response.status_code == 201

    result = await select_route_for_payload(
        session,
        {"operation": "", "output_kind": "semi_finished_shipment", "additional_pack_operations": []},
    )

    assert result.route is not None
    selected = next(candidate for candidate in result.candidate_routes if candidate.route_id == result.route.id)
    assert "WIP_WH" not in selected.section_codes
    assert "SAW" not in selected.section_codes
    assert "PACK" not in selected.section_codes
