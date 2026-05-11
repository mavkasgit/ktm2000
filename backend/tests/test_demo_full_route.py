from decimal import Decimal

import pytest

from app.core.security import create_access_token
from app.models.product import Product, ProductType
from app.models.production_plan import PlanPosition, ProductionPlan, ProductionPlanStatus
from app.models.route import ProductionRoute, RouteStep
from app.models.section import Section
from app.models.techcard import Techcard, TechcardLine
from app.models.user import User, UserRole


async def _make_user(session, email: str = "demo@test.local") -> User:
    user = User(email=email, password_hash="x", full_name="Demo Operator", role=UserRole.operator, is_active=True)
    session.add(user)
    await session.flush()
    return user


def _auth_headers(user: User) -> dict[str, str]:
    token = create_access_token(subject=user.email)
    return {"Authorization": f"Bearer {token}"}


@pytest.mark.asyncio
async def test_demo_full_route_run_and_replay(client, session) -> None:
    user = await _make_user(session)
    headers = _auth_headers(user)

    product = Product(sku="DEMO-FG-001", name="Demo Product", type=ProductType.finished_good, unit="pcs", is_active=True)
    session.add(product)
    await session.flush()

    techcard = Techcard(product_id=product.id, version="v1", is_active=True)
    session.add(techcard)
    await session.flush()
    session.add(
        TechcardLine(
            techcard_id=techcard.id,
            component_product_id=product.id,
            quantity=Decimal("1"),
            unit="pcs",
        )
    )

    sections = [
        Section(code="DEMO-A", name="Demo A", kind="production", is_active=True),
        Section(code="DEMO-B", name="Demo B", kind="production", is_active=True),
        Section(code="DEMO-C", name="Demo C", kind="production", is_active=True),
    ]
    session.add_all(sections)
    await session.flush()

    route = ProductionRoute(name="Demo Full Route", description="A->B->C", is_active=True)
    session.add(route)
    await session.flush()
    for idx, section in enumerate(sections, start=1):
        session.add(
            RouteStep(
                route_id=route.id,
                sequence=idx,
                section_id=section.id,
                operation_code=f"OP{idx}",
                operation_name=f"Operation {idx}",
                is_final=idx == len(sections),
            )
        )
    await session.commit()

    run_id = "demo-run-001"
    response = await client.post(
        "/api/demo/test-runs/full-route",
        json={
            "initial_quantity": "100",
            "techcard_id": techcard.id,
            "route_id": route.id,
            "run_id": run_id,
            "stage_preset": "full_route",
        },
        headers=headers,
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["run_id"] == run_id
    assert body["plan_position_id"] > 0
    assert body["production_plan_id"] > 0
    assert body["route_id"] == route.id
    assert body["tasks_created"] == 3
    assert body["stage_preset"] == "full_route"
    assert body["stopped_at_stage"] == "completed"
    assert len(body["stage_results"]) == 3
    assert all(1 <= int(stage["defect_percent"]) <= 10 for stage in body["stage_results"])

    # Test strict uniqueness: duplicate run_id should return 409
    replay = await client.post(
        "/api/demo/test-runs/full-route",
        json={
            "initial_quantity": "100",
            "techcard_id": techcard.id,
            "route_id": route.id,
            "run_id": run_id,
            "stage_preset": "full_route",
        },
        headers=headers,
    )
    assert replay.status_code == 409, replay.text


@pytest.mark.asyncio
async def test_demo_full_route_forks_when_target_plan_released(client, session) -> None:
    user = await _make_user(session, email="demo2@test.local")
    headers = _auth_headers(user)

    released_plan = ProductionPlan(
        plan_no="PLAN-REL-001",
        name="Released Plan",
        status=ProductionPlanStatus.released,
    )
    session.add(released_plan)

    product = Product(sku="DEMO-FG-002", name="Demo Product 2", type=ProductType.finished_good, unit="pcs", is_active=True)
    session.add(product)
    await session.flush()

    techcard = Techcard(product_id=product.id, version="v1", is_active=True)
    session.add(techcard)
    await session.flush()
    session.add(
        TechcardLine(
            techcard_id=techcard.id,
            component_product_id=product.id,
            quantity=Decimal("1"),
            unit="pcs",
        )
    )

    sections = [
        Section(code="DEMO2-A", name="Demo2 A", kind="production", is_active=True),
        Section(code="DEMO2-B", name="Demo2 B", kind="production", is_active=True),
    ]
    session.add_all(sections)
    await session.flush()

    route = ProductionRoute(name="Demo Route 2", description="A->B", is_active=True)
    session.add(route)
    await session.flush()
    for idx, section in enumerate(sections, start=1):
        session.add(
            RouteStep(
                route_id=route.id,
                sequence=idx,
                section_id=section.id,
                operation_code=f"D2OP{idx}",
                operation_name=f"Demo2 Operation {idx}",
                is_final=idx == len(sections),
            )
        )
    await session.commit()

    response = await client.post(
        "/api/demo/test-runs/full-route",
        json={
            "initial_quantity": "100",
            "techcard_id": techcard.id,
            "route_id": route.id,
            "production_plan_id": released_plan.id,
            "stage_preset": "full_route",
        },
        headers=headers,
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["production_plan_id"] != released_plan.id
    assert body["tasks_created"] == 2


@pytest.mark.asyncio
async def test_demo_stage_preset_before_approve(client, session) -> None:
    user = await _make_user(session, email="before-approve@test.local")
    headers = _auth_headers(user)

    product = Product(sku="DEMO-BA-001", name="Demo BA Product", type=ProductType.finished_good, unit="pcs", is_active=True)
    session.add(product)
    await session.flush()

    techcard = Techcard(product_id=product.id, version="v1", is_active=True)
    session.add(techcard)
    await session.flush()
    session.add(
        TechcardLine(
            techcard_id=techcard.id,
            component_product_id=product.id,
            quantity=Decimal("1"),
            unit="pcs",
        )
    )

    sections = [
        Section(code="DEMO-BA-A", name="Demo BA A", kind="production", is_active=True),
    ]
    session.add_all(sections)
    await session.flush()

    route = ProductionRoute(name="Demo BA Route", description="A", is_active=True)
    session.add(route)
    await session.flush()
    session.add(
        RouteStep(
            route_id=route.id,
            sequence=1,
            section_id=sections[0].id,
            operation_code="BA-OP1",
            operation_name="BA Operation 1",
            is_final=True,
        )
    )
    await session.commit()

    response = await client.post(
        "/api/demo/test-runs/full-route",
        json={
            "initial_quantity": "100",
            "techcard_id": techcard.id,
            "route_id": route.id,
            "run_id": "demo-ba-001",
            "stage_preset": "before_approve",
        },
        headers=headers,
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["stage_preset"] == "before_approve"
    assert body["stopped_at_stage"] == "import_applied"
    assert body["tasks_created"] == 0
    assert len(body["stage_results"]) == 0


@pytest.mark.asyncio
async def test_demo_stage_preset_after_approve(client, session) -> None:
    user = await _make_user(session, email="after-approve@test.local")
    headers = _auth_headers(user)

    product = Product(sku="DEMO-AA-001", name="Demo AA Product", type=ProductType.finished_good, unit="pcs", is_active=True)
    session.add(product)
    await session.flush()

    techcard = Techcard(product_id=product.id, version="v1", is_active=True)
    session.add(techcard)
    await session.flush()
    session.add(
        TechcardLine(
            techcard_id=techcard.id,
            component_product_id=product.id,
            quantity=Decimal("1"),
            unit="pcs",
        )
    )

    sections = [
        Section(code="DEMO-AA-A", name="Demo AA A", kind="production", is_active=True),
    ]
    session.add_all(sections)
    await session.flush()

    route = ProductionRoute(name="Demo AA Route", description="A", is_active=True)
    session.add(route)
    await session.flush()
    session.add(
        RouteStep(
            route_id=route.id,
            sequence=1,
            section_id=sections[0].id,
            operation_code="AA-OP1",
            operation_name="AA Operation 1",
            is_final=True,
        )
    )
    await session.commit()

    response = await client.post(
        "/api/demo/test-runs/full-route",
        json={
            "initial_quantity": "100",
            "techcard_id": techcard.id,
            "route_id": route.id,
            "run_id": "demo-aa-001",
            "stage_preset": "after_approve",
        },
        headers=headers,
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["stage_preset"] == "after_approve"
    assert body["stopped_at_stage"] == "approved"
    assert body["tasks_created"] == 0
    assert len(body["stage_results"]) == 0


@pytest.mark.asyncio
async def test_demo_stage_preset_after_release(client, session) -> None:
    user = await _make_user(session, email="after-release@test.local")
    headers = _auth_headers(user)

    product = Product(sku="DEMO-AR-001", name="Demo AR Product", type=ProductType.finished_good, unit="pcs", is_active=True)
    session.add(product)
    await session.flush()

    techcard = Techcard(product_id=product.id, version="v1", is_active=True)
    session.add(techcard)
    await session.flush()
    session.add(
        TechcardLine(
            techcard_id=techcard.id,
            component_product_id=product.id,
            quantity=Decimal("1"),
            unit="pcs",
        )
    )

    sections = [
        Section(code="DEMO-AR-A", name="Demo AR A", kind="production", is_active=True),
        Section(code="DEMO-AR-B", name="Demo AR B", kind="production", is_active=True),
    ]
    session.add_all(sections)
    await session.flush()

    route = ProductionRoute(name="Demo AR Route", description="A->B", is_active=True)
    session.add(route)
    await session.flush()
    for idx, section in enumerate(sections, start=1):
        session.add(
            RouteStep(
                route_id=route.id,
                sequence=idx,
                section_id=section.id,
                operation_code=f"AR-OP{idx}",
                operation_name=f"AR Operation {idx}",
                is_final=idx == len(sections),
            )
        )
    await session.commit()

    response = await client.post(
        "/api/demo/test-runs/full-route",
        json={
            "initial_quantity": "100",
            "techcard_id": techcard.id,
            "route_id": route.id,
            "run_id": "demo-ar-001",
            "stage_preset": "after_release",
        },
        headers=headers,
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["stage_preset"] == "after_release"
    assert body["stopped_at_stage"] == "released"
    assert body["tasks_created"] == 2
    assert len(body["stage_results"]) == 0


@pytest.mark.asyncio
async def test_demo_stage_preset_to_step_ready_first_step(client, session) -> None:
    user = await _make_user(session, email="to-step-ready@test.local")
    headers = _auth_headers(user)

    product = Product(sku="DEMO-TSR-001", name="Demo TSR Product", type=ProductType.finished_good, unit="pcs", is_active=True)
    session.add(product)
    await session.flush()

    techcard = Techcard(product_id=product.id, version="v1", is_active=True)
    session.add(techcard)
    await session.flush()
    session.add(
        TechcardLine(
            techcard_id=techcard.id,
            component_product_id=product.id,
            quantity=Decimal("1"),
            unit="pcs",
        )
    )

    sections = [
        Section(code="DEMO-TSR-A", name="Demo TSR A", kind="production", is_active=True),
        Section(code="DEMO-TSR-B", name="Demo TSR B", kind="production", is_active=True),
        Section(code="DEMO-TSR-C", name="Demo TSR C", kind="production", is_active=True),
    ]
    session.add_all(sections)
    await session.flush()

    route = ProductionRoute(name="Demo TSR Route", description="A->B->C", is_active=True)
    session.add(route)
    await session.flush()
    route_steps = []
    for idx, section in enumerate(sections, start=1):
        step = RouteStep(
            route_id=route.id,
            sequence=idx,
            section_id=section.id,
            operation_code=f"TSR-OP{idx}",
            operation_name=f"TSR Operation {idx}",
            is_final=idx == len(sections),
        )
        session.add(step)
        route_steps.append(step)
    await session.commit()

    # Target first step: no steps should be executed
    first_step_id = route_steps[0].id
    response = await client.post(
        "/api/demo/test-runs/full-route",
        json={
            "initial_quantity": "100",
            "techcard_id": techcard.id,
            "route_id": route.id,
            "run_id": "demo-tsr-001",
            "stage_preset": "to_step_ready",
            "target_route_step_id": first_step_id,
        },
        headers=headers,
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["stage_preset"] == "to_step_ready"
    assert body["stopped_at_stage"] == f"step_{first_step_id}_ready"
    assert body["tasks_created"] == 0
    assert len(body["stage_results"]) == 0


@pytest.mark.asyncio
async def test_demo_stage_preset_to_step_ready_middle_step(client, session) -> None:
    user = await _make_user(session, email="to-step-ready-mid@test.local")
    headers = _auth_headers(user)

    product = Product(sku="DEMO-TSRM-001", name="Demo TSRM Product", type=ProductType.finished_good, unit="pcs", is_active=True)
    session.add(product)
    await session.flush()

    techcard = Techcard(product_id=product.id, version="v1", is_active=True)
    session.add(techcard)
    await session.flush()
    session.add(
        TechcardLine(
            techcard_id=techcard.id,
            component_product_id=product.id,
            quantity=Decimal("1"),
            unit="pcs",
        )
    )

    sections = [
        Section(code="DEMO-TSRM-A", name="Demo TSRM A", kind="production", is_active=True),
        Section(code="DEMO-TSRM-B", name="Demo TSRM B", kind="production", is_active=True),
        Section(code="DEMO-TSRM-C", name="Demo TSRM C", kind="production", is_active=True),
    ]
    session.add_all(sections)
    await session.flush()

    route = ProductionRoute(name="Demo TSRM Route", description="A->B->C", is_active=True)
    session.add(route)
    await session.flush()
    route_steps = []
    for idx, section in enumerate(sections, start=1):
        step = RouteStep(
            route_id=route.id,
            sequence=idx,
            section_id=section.id,
            operation_code=f"TSRM-OP{idx}",
            operation_name=f"TSRM Operation {idx}",
            is_final=idx == len(sections),
        )
        session.add(step)
        route_steps.append(step)
    await session.commit()

    # Target middle step (step 2): step 1 should be executed, step 2 stays ready
    target_step_id = route_steps[1].id
    response = await client.post(
        "/api/demo/test-runs/full-route",
        json={
            "initial_quantity": "100",
            "techcard_id": techcard.id,
            "route_id": route.id,
            "run_id": "demo-tsrm-001",
            "stage_preset": "to_step_ready",
            "target_route_step_id": target_step_id,
        },
        headers=headers,
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["stage_preset"] == "to_step_ready"
    assert body["stopped_at_stage"] == f"step_{target_step_id}_ready"
    assert body["tasks_created"] == 1  # Only step 1 executed
    assert len(body["stage_results"]) == 1
    assert body["stage_results"][0]["section_code"] == "DEMO-TSRM-A"


@pytest.mark.asyncio
async def test_demo_paired_profile_scenario_imports_as_paired_row(client, session) -> None:
    user = await _make_user(session, email="paired-scenario@test.local")
    headers = _auth_headers(user)

    product = Product(
        sku="ЮП-2616+ЮП-2604",
        name="Paired 2616/2604",
        type=ProductType.finished_good,
        unit="pcs",
        is_active=True,
    )
    session.add(product)
    await session.flush()

    techcard = Techcard(product_id=product.id, version="v1", is_active=True, processing_type="paired_processing")
    session.add(techcard)
    await session.flush()
    session.add(
        TechcardLine(
            techcard_id=techcard.id,
            component_product_id=product.id,
            quantity=Decimal("1"),
            unit="pcs",
        )
    )

    section = Section(code="DEMO-PAIR-A", name="Demo Pair A", kind="production", is_active=True)
    session.add(section)
    await session.flush()

    route = ProductionRoute(name="Demo Pair Route", description="A", is_active=True)
    session.add(route)
    await session.flush()
    session.add(
        RouteStep(
            route_id=route.id,
            sequence=1,
            section_id=section.id,
            operation_code="PAIR-OP1",
            operation_name="Pair Operation 1",
            is_final=True,
        )
    )
    await session.commit()

    response = await client.post(
        "/api/demo/test-runs/full-route",
        json={
            "initial_quantity": "100",
            "techcard_id": techcard.id,
            "route_id": route.id,
            "run_id": "demo-pair-001",
            "stage_preset": "before_approve",
            "scenario_id": "paired_2616_2604_sf",
        },
        headers=headers,
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["stage_preset"] == "before_approve"

    position = await session.get(PlanPosition, body["plan_position_id"])
    assert position is not None
    source_payload = position.source_payload or {}
    assert source_payload.get("paired_profile") is True
    components = source_payload.get("components") or []
    assert len(components) == 2
    component_skus = [component.get("sku") for component in components]
    assert "ЮП-2616" in component_skus
    assert "ЮП-2604" in component_skus
