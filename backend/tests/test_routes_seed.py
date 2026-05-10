import pytest

from app.models.section import Section


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
async def test_seed_routes_creates_six_typical_routes(client, session) -> None:
    for item in DEFAULT_SECTIONS:
        session.add(Section(code=item["code"], name=item["name"], sort_order=item["sort_order"], kind=item["kind"], is_active=True))
    await session.commit()

    response = await client.post("/api/routes-seed")
    assert response.status_code == 201
    data = response.json()
    assert len(data) == 6
    names = [route["name"] for route in data]
    assert "Типовой: полный (все участки)" in names
    assert "Типовой: без сверла" in names
    assert "Типовой: без пресса и сверла" in names
    assert "Типовой: без пресса, сверла и дробеструя" in names
    assert "Типовой: без сверла, пресса и упаковки" in names
    assert "Типовой: отгрузочный" in names

    # idempotency/update behavior
    response2 = await client.post("/api/routes-seed")
    assert response2.status_code == 201
    data2 = response2.json()
    assert len(data2) == 6
