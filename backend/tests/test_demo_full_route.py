from decimal import Decimal

import pytest

from app.core.security import create_access_token
from app.models.product import Product, ProductType
from app.models.production_plan import PlanPosition, ProductionPlan, ProductionPlanStatus
from app.models.route import ProductionRoute, RouteStep
from app.models.routing import RouteOperationFamily, RouteOutputKind
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


async def _make_demo_route(session, code_prefix: str, step_defs: list[tuple[str, str, str, bool]]) -> ProductionRoute:
    """Create sections and a route with proper operation codes and section kinds.

    step_defs: list of (section_code_suffix, operation_code, operation_name, is_final)
    """
    kind_map = {
        "ISSUE_RAW": "raw_stock",
        "MOVE_TO_WIP": "wip_stock",
        "ACCEPT_FINISHED": "finished_stock",
    }
    sections = []
    for suffix, op_code, op_name, _ in step_defs:
        kind = kind_map.get(op_code, "production")
        sections.append(Section(code=f"{code_prefix}-{suffix}", name=op_name, kind=kind, is_active=True))
    session.add_all(sections)
    await session.flush()

    route = ProductionRoute(name=f"Demo Route {code_prefix}", description="Demo", is_active=True)
    session.add(route)
    await session.flush()

    for idx, (suffix, op_code, op_name, is_final) in enumerate(step_defs, start=1):
        session.add(
            RouteStep(
                route_id=route.id,
                sequence=idx,
                section_id=sections[idx - 1].id,
                operation_code=op_code,
                operation_name=op_name,
                is_final=is_final,
            )
        )
    await session.commit()
    return route


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

    route_steps_def = [
        ("ISSUE", "ISSUE_RAW", "Выдача сырья", False),
        ("SHOT", "SHOT", "Дробеструй", False),
        ("ANOD", "ANOD", "Анодирование", False),
        ("WIP", "MOVE_TO_WIP", "Перед. на склад п/ф", False),
        ("SAW", "SAW", "Резка на пиле", False),
        ("PACK", "PACK", "Упаковка", False),
        ("FG_WH", "ACCEPT_FINISHED", "Приемка ГП", True),
    ]
    route = await _make_demo_route(session, "DEMO-001", route_steps_def)

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
    assert body["tasks_created"] == 7
    assert body["stage_preset"] == "full_route"
    assert body["stopped_at_stage"] == "completed"
    assert len(body["stage_results"]) == 7
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

    route_steps_def = [
        ("ISSUE", "ISSUE_RAW", "Выдача сырья", False),
        ("SHOT", "SHOT", "Дробеструй", False),
        ("ANOD", "ANOD", "Анодирование", False),
        ("WIP", "MOVE_TO_WIP", "Перед. на склад п/ф", False),
        ("SAW", "SAW", "Резка на пиле", False),
        ("PACK", "PACK", "Упаковка", False),
        ("FG_WH", "ACCEPT_FINISHED", "Приемка ГП", True),
    ]
    route = await _make_demo_route(session, "DEMO-002", route_steps_def)

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
    assert body["tasks_created"] == 7


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

    route_steps_def = [
        ("ISSUE", "ISSUE_RAW", "Выдача сырья", False),
        ("SHOT", "SHOT", "Дробеструй", False),
        ("ANOD", "ANOD", "Анодирование", False),
        ("WIP", "MOVE_TO_WIP", "Перед. на склад п/ф", False),
        ("SAW", "SAW", "Резка на пиле", False),
        ("PACK", "PACK", "Упаковка", False),
        ("FG_WH", "ACCEPT_FINISHED", "Приемка ГП", True),
    ]
    route = await _make_demo_route(session, "DEMO-AR", route_steps_def)

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
    assert body["tasks_created"] == 7
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

    route_steps_def = [
        ("ISSUE", "ISSUE_RAW", "Выдача сырья", False),
        ("SHOT", "SHOT", "Дробеструй", False),
        ("ANOD", "ANOD", "Анодирование", False),
        ("WIP", "MOVE_TO_WIP", "Перед. на склад п/ф", False),
        ("SAW", "SAW", "Резка на пиле", False),
        ("PACK", "PACK", "Упаковка", False),
        ("FG_WH", "ACCEPT_FINISHED", "Приемка ГП", True),
    ]
    route = await _make_demo_route(session, "DEMO-TSR", route_steps_def)

    # Get the first route step id
    from sqlalchemy import select as sa_select
    first_step = await session.scalar(
        sa_select(RouteStep).where(RouteStep.route_id == route.id).order_by(RouteStep.sequence).limit(1)
    )

    # Target first step: no steps should be executed
    response = await client.post(
        "/api/demo/test-runs/full-route",
        json={
            "initial_quantity": "100",
            "techcard_id": techcard.id,
            "route_id": route.id,
            "run_id": "demo-tsr-001",
            "stage_preset": "to_step_ready",
            "target_route_step_id": first_step.id,
        },
        headers=headers,
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["stage_preset"] == "to_step_ready"
    assert body["stopped_at_stage"] == f"step_{first_step.id}_ready"
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

    route_steps_def = [
        ("ISSUE", "ISSUE_RAW", "Выдача сырья", False),
        ("SHOT", "SHOT", "Дробеструй", False),
        ("ANOD", "ANOD", "Анодирование", False),
        ("WIP", "MOVE_TO_WIP", "Перед. на склад п/ф", False),
        ("SAW", "SAW", "Резка на пиле", False),
        ("PACK", "PACK", "Упаковка", False),
        ("FG_WH", "ACCEPT_FINISHED", "Приемка ГП", True),
    ]
    route = await _make_demo_route(session, "DEMO-TSRM", route_steps_def)

    # Get route steps to target middle step (step 3 = ANOD, 0-indexed = 2)
    from sqlalchemy import select as sa_select
    all_steps = (
        await session.execute(
            sa_select(RouteStep).where(RouteStep.route_id == route.id).order_by(RouteStep.sequence)
        )
    ).scalars().all()
    target_step = all_steps[2]  # ANOD (3rd step)

    # Target middle step (step 3): steps 1-2 should be executed, step 3 stays ready
    response = await client.post(
        "/api/demo/test-runs/full-route",
        json={
            "initial_quantity": "100",
            "techcard_id": techcard.id,
            "route_id": route.id,
            "run_id": "demo-tsrm-001",
            "stage_preset": "to_step_ready",
            "target_route_step_id": target_step.id,
        },
        headers=headers,
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["stage_preset"] == "to_step_ready"
    assert body["stopped_at_stage"] == f"step_{target_step.id}_ready"
    assert body["tasks_created"] == 2  # Steps 1-2 executed
    assert len(body["stage_results"]) == 2
    assert body["stage_results"][0]["section_code"].startswith("DEMO-TSRM-ISSUE")


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
