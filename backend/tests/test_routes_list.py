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
    section = Section(code="SEC-STEPS", name="Steps Section")
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