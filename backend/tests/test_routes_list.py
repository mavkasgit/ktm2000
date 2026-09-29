import pytest

from app.models.route import ProductionRoute, RouteStage, RouteOperation
from app.models.section import Section


@pytest.mark.asyncio
async def test_list_routes_without_steps_returns_route_out(client, session) -> None:
    section = Section(code="SEC-LIST", name="List Section")
    session.add(section)
    await session.flush()

    route = ProductionRoute(name="Route List Basic", is_active=True)
    session.add(route)
    await session.flush()

    stage = RouteStage(
        route_id=route.id,
        sequence=1,
        section_id=section.id,
        is_final=True,
        allow_parallel=False,
    )
    session.add(stage)
    await session.flush()
    session.add(RouteOperation(route_stage_id=stage.id, sequence=1, operation_name="Op List"))
    await session.commit()

    response = await client.get("/api/routes")
    assert response.status_code == 200
    data = response.json()
    item = next(row for row in data if row["id"] == route.id)
    assert "steps" not in item
    assert item["name"] == "Route List Basic"


@pytest.mark.asyncio
async def test_list_routes_include_steps_returns_details(client, session) -> None:
    section = Section(
        code="SEC-STEPS",
        name="Steps Section",
        icon="Drill",
        icon_color="#3B82F6",
        type="production",
    )
    session.add(section)
    await session.flush()

    route = ProductionRoute(name="Route With Steps", is_active=True)
    session.add(route)
    await session.flush()

    stage = RouteStage(
        route_id=route.id,
        sequence=1,
        section_id=section.id,
        is_final=False,
        allow_parallel=True,
    )
    session.add(stage)
    await session.flush()
    session.add(
        RouteOperation(
            route_stage_id=stage.id,
            sequence=1,
            operation_code="OP-1",
            operation_name="Assembly",
        )
    )
    await session.commit()

    response = await client.get("/api/routes", params={"include_steps": "true"})
    assert response.status_code == 200
    data = response.json()

    routes_with_steps = [row for row in data if row["id"] == route.id]
    assert len(routes_with_steps) == 1
    detail = routes_with_steps[0]

    assert detail["name"] == "Route With Steps"
    assert "steps" in detail
    assert "rules" in detail
    assert len(detail["steps"]) == 1

    step = detail["steps"][0]
    assert step["section_id"] == section.id
    assert step["icon"] == "Drill"
    assert step["icon_color"] == "#3B82F6"
    assert step["section_type"] == "production"
    assert step["operation_code"] == "OP-1"
    assert step["operation_name"] == "Assembly"
    assert step["allow_parallel"] is True
    assert step["is_final"] is False


@pytest.mark.asyncio
async def test_list_routes_include_steps_count_matches_routes(client, session) -> None:
    section = Section(code="SEC-COUNT", name="Count Section")
    session.add(section)
    await session.flush()

    route_names = ["Route Count A", "Route Count B"]
    for name in route_names:
        route = ProductionRoute(name=name, is_active=True)
        session.add(route)
        await session.flush()
        stage = RouteStage(route_id=route.id, sequence=1, section_id=section.id, is_final=True)
        session.add(stage)
        await session.flush()
        session.add(RouteOperation(route_stage_id=stage.id, sequence=1, operation_name=f"Op {name}"))
    await session.commit()

    list_response = await client.get("/api/routes")
    assert list_response.status_code == 200
    route_count = len(list_response.json())

    detail_response = await client.get("/api/routes", params={"include_steps": "true"})
    assert detail_response.status_code == 200
    detail_data = detail_response.json()
    assert len(detail_data) == route_count
    assert all("steps" in row for row in detail_data)


@pytest.mark.asyncio
async def test_create_route_conflicts_with_import_route_name(client, session) -> None:
    """409 срабатывает и на имени АВТОмаршрута (код не NULL), а не только ручного.

    ADR-0051 снял уникальность имени и ввёл поиск по коду, но ручной API
    сохраняет 409 на совпадение имени — это защита от ошибки оператора
    («Последствия» ADR-0051). Поэтому поиск здесь идёт БЕЗ фильтра по коду:
    с фильтром `code IS NULL` ручной маршрут с именем автомаршрута создался
    бы вторым и молча (уникальность по коду NULL не нарушает).

    Регресс-тест на контракт, откатом не проверяется: правки здесь нет, есть
    риск, что её посчитают лишней при следующем переносе.
    """
    auto_route = ProductionRoute(
        name="ЮП-460 резка", code="auto-0123456789abcdef", is_active=True
    )
    session.add(auto_route)
    await session.commit()

    created = await client.post(
        "/api/routes", json={"name": "ЮП-460 резка", "is_active": True}
    )

    assert created.status_code == 409, created.text
    assert created.json()["detail"] == "Route with this name already exists"


@pytest.mark.asyncio
async def test_update_route_conflicts_with_import_route_name(client, session) -> None:
    """PUT: переименование в имя автомаршрута тоже отбивается 409.

    Тот же контракт, что в POST, плюс ``exclude_id``: маршрут не считается
    конфликтом сам с собой, поэтому переименование в своё же имя проходит.
    """
    auto_route = ProductionRoute(
        name="ЮП-460 резка", code="auto-0123456789abcdef", is_active=True
    )
    manual = ProductionRoute(name="Ручной маршрут", is_active=True)
    session.add_all([auto_route, manual])
    await session.commit()

    forbidden = await client.put(
        f"/api/routes/{manual.id}", json={"name": "ЮП-460 резка"}
    )

    assert forbidden.status_code == 409, forbidden.text
    assert forbidden.json()["detail"] == "Route with this name already exists"

    same_name = await client.put(
        f"/api/routes/{manual.id}", json={"name": manual.name}
    )
    assert same_name.status_code == 200, same_name.text