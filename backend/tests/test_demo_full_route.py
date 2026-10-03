from decimal import Decimal

import pytest
from app.api.routes import demo as demo_routes
from app.core.security import create_access_token
from app.models.product import Product, ProductLength, ProductPair, ProductType
from app.models.production_plan import (
    PlanPosition,
    ProductionPlan,
    ProductionPlanStatus,
)
from app.models.route import ProductionRoute, RouteOperation, RouteStage
from app.models.section import Section
from app.models.user import User, UserRole
from app.services.route_storage_classifier import is_production_section
from sqlalchemy import select

from tests.helpers.completed_operations import register_section_operations


async def _make_demo_product(session, *, sku: str, name: str) -> Product:
    product = Product(
        sku=sku,
        name=name,
        type=ProductType.finished_good,
        unit="pcs",
        is_active=True,
    )
    session.add(product)
    await session.flush()
    session.add(ProductLength(
        product_id=product.id,
        length_mm=2700,
        raw_length_mm=None,
        is_primary=True,
    ))
    await session.flush()
    return product


async def _make_user(session, email: str = "demo@test.local") -> User:
    user = User(email=email, full_name="Demo Operator", role=UserRole.operator, is_active=True)
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
    type_map = {
        "ISSUE_RAW": "raw_stock",
        "MOVE_TO_WIP": "wip_stock",
        "ACCEPT_FINISHED": "finished_stock",
    }
    sections = []
    for suffix, op_code, op_name, _ in step_defs:
        type_val = type_map.get(op_code, "production")
        sections.append(Section(code=f"{code_prefix}-{suffix}", name=op_name, type=type_val, is_active=True))
    session.add_all(sections)
    await session.flush()

    route = ProductionRoute(name=f"Demo Route {code_prefix}", description="Demo", is_active=True)
    session.add(route)
    await session.flush()

    for idx, (suffix, op_code, op_name, is_final) in enumerate(step_defs, start=1):
        section = sections[idx - 1]
        stage = RouteStage(
            route_id=route.id,
            sequence=idx,
            section_id=section.id,
            is_final=is_final,
        )
        session.add(stage)
        await session.flush()
        # Транзитный (складской) этап операции не несёт — так его строит и
        # продовый конструктор маршрута (``if stage_kind == "production"``).
        # Операция на транзите попала бы в признак материала (ADR-0061), а
        # демо-прогон ведёт материал по производственным этапам, минуя склад:
        # прямая передача через склад несла бы признак до своего этапа и
        # разошлась бы со списанием следующего участка.
        if not is_production_section(section):
            continue
        session.add(
            RouteOperation(
                route_stage_id=stage.id,
                sequence=1,
                operation_code=op_code,
                operation_name=op_name,
            )
        )
        # Операция этапа обязана быть и в справочнике участка (ADR-0061):
        # признак «пройденные операции» выводится из операции ЭТАПА, а запись
        # в ledger проверяет коды по ``section_operations``. Продовый маршрут
        # собирается из справочника, тестовая фикстура объявляет операцию
        # прямо на этапе — без дубля код отвергли бы как неизвестный.
        await register_section_operations(session, section.id, [op_code])
    await session.commit()
    return route


async def _seed_demo_stock(
    session, product_id: int, section_id: int, quantity: Decimal = Decimal(100),
    dimensions: dict | None = None,
) -> None:
    """Seed initial stock for demo tests using StockCommandService.

    ADR-0055: расход точный, поэтому демо-сырьё кладётся в ту же
    ops-группу, из которой его заберёт плановая выдача
    (``_ensure_task_issued_via_transfer`` → ``transfer_send`` с фейкового
    складского задания). Признак берётся из маршрута самой складской
    секции — тот же резолвер, что и у ``record()``.
    """
    from app.stock import QualityState, Reason, StockCommand, StockCommandService

    from tests.helpers.transfers import _section_route_operations

    svc = StockCommandService()
    await svc.record(session, StockCommand(
        product_id=product_id,
        quantity=quantity,
        reason=Reason.MANUAL_IN,
        to_location_id=section_id,
        quality_state=QualityState.GOOD,
        dimensions=dimensions,
        completed_operations=await _section_route_operations(session, section_id),
        created_by=1,
        comment="Demo stock seed",
    ))


@pytest.mark.asyncio
async def test_demo_full_route_run_and_replay(client, session) -> None:
    user = await _make_user(session)
    headers = _auth_headers(user)

    product = await _make_demo_product(
        session,
        sku="DEMO-FG-001",
        name="Demo Product",
    )


    route_steps_def = [
        ("ISSUE", "ISSUE_RAW", "Выдача сырья", False),
        ("SHOT_BLAST", "SHOT", "Дробеструй", False),
        ("ANODIZING", "ANOD", "Анодирование", False),
        ("WIP", "MOVE_TO_WIP", "Перед. на склад п/ф", False),
        ("SAWING", "SAW", "Резка на пиле", False),
        ("PACKING", "PACK", "Упаковка", False),
        ("FINISHED_STOCK", "ACCEPT_FINISHED", "Приемка ГП", True),
    ]
    route = await _make_demo_route(session, "DEMO-001", route_steps_def)

    # Seed initial stock into the raw_stock section for the demo run
    raw_section = await session.scalar(
        select(Section).where(Section.code == "DEMO-001-ISSUE")
    )
    await _seed_demo_stock(session, product.id, raw_section.id, Decimal(200),
                           dimensions={"length_mm": 2700})

    run_id = "demo-run-001"
    response = await client.post(
        "/api/demo/test-runs/full-route",
        json={
            "initial_quantity": "100",
            "product_id": product.id,
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
    assert body["tasks_created"] == 4
    assert body["stage_preset"] == "full_route"
    assert body["stopped_at_stage"] == "completed"
    assert len(body["stage_results"]) == 4
    assert all(1 <= int(stage["defect_percent"]) <= 10 for stage in body["stage_results"])

    # Test strict uniqueness: duplicate run_id should return 409
    replay = await client.post(
        "/api/demo/test-runs/full-route",
        json={
            "initial_quantity": "100",
            "product_id": product.id,
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

    product = await _make_demo_product(
        session,
        sku="DEMO-FG-002",
        name="Demo Product 2",
    )


    route_steps_def = [
        ("ISSUE", "ISSUE_RAW", "Выдача сырья", False),
        ("SHOT_BLAST", "SHOT", "Дробеструй", False),
        ("ANODIZING", "ANOD", "Анодирование", False),
        ("WIP", "MOVE_TO_WIP", "Перед. на склад п/ф", False),
        ("SAWING", "SAW", "Резка на пиле", False),
        ("PACKING", "PACK", "Упаковка", False),
        ("FINISHED_STOCK", "ACCEPT_FINISHED", "Приемка ГП", True),
    ]
    route = await _make_demo_route(session, "DEMO-002", route_steps_def)

    # Seed initial stock into the raw_stock section
    raw_section = await session.scalar(
        select(Section).where(Section.code == "DEMO-002-ISSUE")
    )
    await _seed_demo_stock(session, product.id, raw_section.id, Decimal(200),
                           dimensions={"length_mm": 2700})

    response = await client.post(
        "/api/demo/test-runs/full-route",
        json={
            "initial_quantity": "100",
            "product_id": product.id,
            "route_id": route.id,
            "production_plan_id": released_plan.id,
            "stage_preset": "full_route",
        },
        headers=headers,
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["production_plan_id"] != released_plan.id
    assert body["tasks_created"] == 4


@pytest.mark.asyncio
async def test_demo_stage_preset_before_approve(client, session) -> None:
    user = await _make_user(session, email="before-approve@test.local")
    headers = _auth_headers(user)

    product = await _make_demo_product(
        session,
        sku="DEMO-BA-001",
        name="Demo BA Product",
    )


    sections = [
        Section(code="DEMO-BA-A", name="Demo BA A", type="production", is_active=True),
    ]
    session.add_all(sections)
    await session.flush()

    route = ProductionRoute(name="Demo BA Route", description="A", is_active=True)
    session.add(route)
    await session.flush()
    stage = RouteStage(
        route_id=route.id,
        sequence=1,
        section_id=sections[0].id,
        is_final=True,
    )
    session.add(stage)
    await session.flush()
    session.add(
        RouteOperation(
            route_stage_id=stage.id,
            sequence=1,
            operation_code="BA-OP1",
            operation_name="BA Operation 1",
        )
    )
    await session.commit()

    response = await client.post(
        "/api/demo/test-runs/full-route",
        json={
            "initial_quantity": "100",
            "product_id": product.id,
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

    product = await _make_demo_product(
        session,
        sku="DEMO-AA-001",
        name="Demo AA Product",
    )


    sections = [
        Section(code="DEMO-AA-A", name="Demo AA A", type="production", is_active=True),
    ]
    session.add_all(sections)
    await session.flush()

    route = ProductionRoute(name="Demo AA Route", description="A", is_active=True)
    session.add(route)
    await session.flush()
    stage = RouteStage(
        route_id=route.id,
        sequence=1,
        section_id=sections[0].id,
        is_final=True,
    )
    session.add(stage)
    await session.flush()
    session.add(
        RouteOperation(
            route_stage_id=stage.id,
            sequence=1,
            operation_code="AA-OP1",
            operation_name="AA Operation 1",
        )
    )
    await session.commit()

    response = await client.post(
        "/api/demo/test-runs/full-route",
        json={
            "initial_quantity": "100",
            "product_id": product.id,
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

    product = await _make_demo_product(
        session,
        sku="DEMO-AR-001",
        name="Demo AR Product",
    )


    route_steps_def = [
        ("ISSUE", "ISSUE_RAW", "Выдача сырья", False),
        ("SHOT_BLAST", "SHOT", "Дробеструй", False),
        ("ANODIZING", "ANOD", "Анодирование", False),
        ("WIP", "MOVE_TO_WIP", "Перед. на склад п/ф", False),
        ("SAWING", "SAW", "Резка на пиле", False),
        ("PACKING", "PACK", "Упаковка", False),
        ("FINISHED_STOCK", "ACCEPT_FINISHED", "Приемка ГП", True),
    ]
    route = await _make_demo_route(session, "DEMO-AR", route_steps_def)

    response = await client.post(
        "/api/demo/test-runs/full-route",
        json={
            "initial_quantity": "100",
            "product_id": product.id,
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
    assert body["tasks_created"] == 4
    assert len(body["stage_results"]) == 0


@pytest.mark.asyncio
async def test_demo_stage_preset_to_step_ready_first_step(client, session) -> None:
    user = await _make_user(session, email="to-step-ready@test.local")
    headers = _auth_headers(user)

    product = await _make_demo_product(
        session,
        sku="DEMO-TSR-001",
        name="Demo TSR Product",
    )


    route_steps_def = [
        ("ISSUE", "ISSUE_RAW", "Выдача сырья", False),
        ("SHOT_BLAST", "SHOT", "Дробеструй", False),
        ("ANODIZING", "ANOD", "Анодирование", False),
        ("WIP", "MOVE_TO_WIP", "Перед. на склад п/ф", False),
        ("SAWING", "SAW", "Резка на пиле", False),
        ("PACKING", "PACK", "Упаковка", False),
        ("FINISHED_STOCK", "ACCEPT_FINISHED", "Приемка ГП", True),
    ]
    route = await _make_demo_route(session, "DEMO-TSR", route_steps_def)

    # Get the first production route stage (SHOT_BLAST, seq 2)
    # ISSUE (seq 1) is raw_stock — no WorkTask, so it won't appear in task_rows
    from sqlalchemy import select as sa_select
    all_route_stages = (
        await session.execute(
            sa_select(RouteStage).where(RouteStage.route_id == route.id).order_by(RouteStage.sequence)
        )
    ).scalars().all()
    first_production_stage = all_route_stages[1]  # SHOT_BLAST (seq 2)

    # Target first production step: no steps should be executed
    response = await client.post(
        "/api/demo/test-runs/full-route",
        json={
            "initial_quantity": "100",
            "product_id": product.id,
            "route_id": route.id,
            "run_id": "demo-tsr-001",
            "stage_preset": "to_step_ready",
            "target_route_stage_id": first_production_stage.id,
        },
        headers=headers,
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["stage_preset"] == "to_step_ready"
    assert body["stopped_at_stage"] == f"step_{first_production_stage.id}_ready"
    assert body["tasks_created"] == 0
    assert len(body["stage_results"]) == 0


@pytest.mark.asyncio
async def test_demo_stage_preset_to_step_ready_middle_step(client, session) -> None:
    user = await _make_user(session, email="to-step-ready-mid@test.local")
    headers = _auth_headers(user)

    product = await _make_demo_product(
        session,
        sku="DEMO-TSRM-001",
        name="Demo TSRM Product",
    )


    route_steps_def = [
        ("ISSUE", "ISSUE_RAW", "Выдача сырья", False),
        ("SHOT_BLAST", "SHOT", "Дробеструй", False),
        ("ANODIZING", "ANOD", "Анодирование", False),
        ("WIP", "MOVE_TO_WIP", "Перед. на склад п/ф", False),
        ("SAWING", "SAW", "Резка на пиле", False),
        ("PACKING", "PACK", "Упаковка", False),
        ("FINISHED_STOCK", "ACCEPT_FINISHED", "Приемка ГП", True),
    ]
    route = await _make_demo_route(session, "DEMO-TSRM", route_steps_def)

    # Seed initial stock into the raw_stock section
    raw_section = await session.scalar(
        select(Section).where(Section.code == "DEMO-TSRM-ISSUE")
    )
    await _seed_demo_stock(session, product.id, raw_section.id, Decimal(200),
                           dimensions={"length_mm": 2700})

    # Target 3rd production step (SAWING): execute SHOT_BLAST + ANODIZING, leave SAWING ready.
    # Route stages: ISSUE (raw_stock), SHOT, ANOD, WIP (wip_stock), SAW, PACK, FG (finished_stock).
    # WorkTasks exist only on production sections: SHOT_BLAST, ANODIZING, SAWING, PACKING.
    from sqlalchemy import select as sa_select
    all_stages = (
        await session.execute(
            sa_select(RouteStage).where(RouteStage.route_id == route.id).order_by(RouteStage.sequence)
        )
    ).scalars().all()
    target_stage = all_stages[4]  # SAWING — 3rd production task in task_rows

    # Execute indices [0, 1] (SHOT_BLAST, ANODIZING) → 2 tasks, stop before SAWING
    response = await client.post(
        "/api/demo/test-runs/full-route",
        json={
            "initial_quantity": "100",
            "product_id": product.id,
            "route_id": route.id,
            "run_id": "demo-tsrm-001",
            "stage_preset": "to_step_ready",
            "target_route_stage_id": target_stage.id,
        },
        headers=headers,
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["stage_preset"] == "to_step_ready"
    assert body["stopped_at_stage"] == f"step_{target_stage.id}_ready"
    assert body["tasks_created"] == 2  # SHOT_BLAST + ANODIZING executed
    assert len(body["stage_results"]) == 2
    assert body["stage_results"][0]["section_code"] == "DEMO-TSRM-SHOT_BLAST"


@pytest.mark.asyncio
async def test_demo_paired_profile_scenario_imports_as_paired_row(
    client, session, monkeypatch
) -> None:
    """Демо-прогон по сценарию парного профиля даёт позицию с двумя компонентами.

    Сценарий подставляется прямо здесь: справочник сценариев лежит в
    ``backend/data/`` — каталоге рантайма (``.gitignore``), которого нет в
    репозитории и у которого нет генератора. Тест не должен зависеть от
    файла, которого в чистом checkout не бывает.
    """
    user = await _make_user(session, email="paired-scenario@test.local")
    headers = _auth_headers(user)

    monkeypatch.setattr(
        demo_routes,
        "_scenario_map",
        lambda: {
            "paired_2616_2604_sf": {
                "scenario_id": "paired_2616_2604_sf",
                "primary_sku": "ЮП-2616",
                "secondary_sku": "ЮП-2604",
                "output_kind_raw": "ГП",
            }
        },
    )

    product = await _make_demo_product(
        session,
        sku="ЮП-2616+ЮП-2604",
        name="Paired 2616/2604",
    )


    # Пара резолвится из product_pairs (#148): сырьевые артикулы сценария
    # + ручная N на общей длине 2700 мм.

    raw_a = Product(sku="ЮП-2616", name="Raw 2616", type=ProductType.component, unit="pcs", is_active=True)
    raw_b = Product(sku="ЮП-2604", name="Raw 2604", type=ProductType.component, unit="pcs", is_active=True)
    session.add_all([raw_a, raw_b])
    await session.flush()
    session.add_all([
        ProductLength(product_id=raw_a.id, length_mm=2700, raw_length_mm=None, is_primary=True),
        ProductLength(product_id=raw_b.id, length_mm=2700, raw_length_mm=None, is_primary=True),
    ])
    session.add(ProductPair(
        product_a_id=min(raw_a.id, raw_b.id),
        product_b_id=max(raw_a.id, raw_b.id),
        quantity_per_hanger={"2700": {"auto": None, "manual": 8}},
    ))

    section = Section(code="DEMO-PAIR-A", name="Demo Pair A", type="production", is_active=True)
    session.add(section)
    await session.flush()

    route = ProductionRoute(name="Demo Pair Route", description="A", is_active=True)
    session.add(route)
    await session.flush()
    stage = RouteStage(
        route_id=route.id,
        sequence=1,
        section_id=section.id,
        is_final=True,
    )
    session.add(stage)
    await session.flush()
    session.add(
        RouteOperation(
            route_stage_id=stage.id,
            sequence=1,
            operation_code="PAIR-OP1",
            operation_name="Pair Operation 1",
        )
    )
    await session.commit()

    response = await client.post(
        "/api/demo/test-runs/full-route",
        json={
            "initial_quantity": "100",
            "product_id": product.id,
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


@pytest.mark.asyncio
async def test_demo_picks_active_route_over_archived_with_smaller_id(client, session) -> None:
    """Поиск по имени берёт АКТИВНЫЙ маршрут, даже если архивный старше.

    Поиск demo шёл по имени без фильтра по активности и брал самый старый
    (``order_by(id)``): при двух одноимённых маршрутах в выпуск уходил
    архивный. Теперь фильтр внутри поиска (``only_active``), и порядок общий.
    """
    user = await _make_user(session, email="demo-active@test.local")
    headers = _auth_headers(user)
    product = await _make_demo_product(session, sku="DEMO-ACT-001", name="Active route product")

    route_steps_def = [
        ("ISSUE", "ISSUE_RAW", "Выдача сырья", False),
        ("SHOT_BLAST", "SHOT", "Дробеструй", False),
        ("ANODIZING", "ANOD", "Анодирование", False),
        ("WIP", "MOVE_TO_WIP", "Перед. на склад п/ф", False),
        ("SAWING", "SAW", "Резка на пиле", False),
        ("PACKING", "PACK", "Упаковка", False),
        ("FINISHED_STOCK", "ACCEPT_FINISHED", "Приемка ГП", True),
    ]
    # Архивный создаём ПЕРВЫМ — у него меньший id. Имя у обоих общее: иначе
    # это не дубль, а разные маршруты, и порядок выборки не имеет значения.
    archived = await _make_demo_route(session, "DEMO-ACT-OLD", route_steps_def)
    archived.is_active = False
    await session.commit()

    active = await _make_demo_route(session, "DEMO-ACT-NEW", route_steps_def)
    active.name = archived.name
    await session.commit()
    assert archived.id < active.id, "предусловие: архивный должен быть старше"

    raw_section = await session.scalar(
        select(Section).where(Section.code == "DEMO-ACT-NEW-ISSUE")
    )
    await _seed_demo_stock(session, product.id, raw_section.id, Decimal(200),
                           dimensions={"length_mm": 2700})

    response = await client.post(
        "/api/demo/test-runs/full-route",
        json={
            "initial_quantity": "100",
            "product_id": product.id,
            "route_name": active.name,
            "run_id": "demo-active-001",
            "stage_preset": "full_route",
        },
        headers=headers,
    )

    assert response.status_code == 200, response.text
    assert response.json()["route_id"] == active.id, "взялся архивный маршрут"


@pytest.mark.asyncio
async def test_demo_archived_only_route_still_answers_inactive(client, session) -> None:
    """Ответ про архивный маршрут прежний: 400 по id, 404 по имени.

    Проверка ``not route.is_active`` осталась на месте — при явном ``route_id``
    отказ «маршрут отключён», а не «маршрут не найден». Здесь маршрут ищется
    по имени, его отсекает фильтр поиска, и наступает 404. Оба ответа
    зафиксированы с кодом и текстом, чтобы перенос фильтра не поменял их
    молча.
    """
    user = await _make_user(session, email="demo-arch@test.local")
    headers = _auth_headers(user)
    product = await _make_demo_product(session, sku="DEMO-ARCH-001", name="Archived route product")

    route_steps_def = [
        ("ISSUE", "ISSUE_RAW", "Выдача сырья", False),
        ("SHOT_BLAST", "SHOT", "Дробеструй", False),
        ("ANODIZING", "ANOD", "Анодирование", False),
        ("WIP", "MOVE_TO_WIP", "Перед. на склад п/ф", False),
        ("SAWING", "SAW", "Резка на пиле", False),
        ("PACKING", "PACK", "Упаковка", False),
        ("FINISHED_STOCK", "ACCEPT_FINISHED", "Приемка ГП", True),
    ]
    archived = await _make_demo_route(session, "DEMO-ARCH", route_steps_def)
    archived.is_active = False
    await session.commit()

    by_id = await client.post(
        "/api/demo/test-runs/full-route",
        json={
            "initial_quantity": "100",
            "product_id": product.id,
            "route_id": archived.id,
            "run_id": "demo-arch-by-id",
            "stage_preset": "full_route",
        },
        headers=headers,
    )
    assert by_id.status_code == 400, by_id.text
    assert by_id.json()["detail"] == "Маршрут неактивен", by_id.text

    by_name = await client.post(
        "/api/demo/test-runs/full-route",
        json={
            "initial_quantity": "100",
            "product_id": product.id,
            "route_name": archived.name,
            "run_id": "demo-arch-by-name",
            "stage_preset": "full_route",
        },
        headers=headers,
    )
    assert by_name.status_code == 404, by_name.text
    assert by_name.json()["detail"] == "Маршрут не найден", by_name.text
