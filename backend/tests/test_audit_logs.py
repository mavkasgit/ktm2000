import pytest
from app.models.work_task import WorkTask, WorkTaskStatus
from app.models.product import Product, ProductType
from app.models.route import RouteStage
from app.models.section import Section
from app.models.audit_log import AuditLog


@pytest.mark.asyncio
async def test_create_audit_log(client, session) -> None:
    # User is seeded globally in conftest.py

    response = await client.post(
        "/api/audit-logs",
        json={
            "status": "success",
            "title": "Тестовое событие",
            "message": "Всё работает отлично!",
            "product_sku": "SKU-TEST-123",
            "qty_text": "годн: 10, брак: 1",
            "comment": "Тест-коммент",
            "task_ids": [101, 102],
        },
    )

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "success"
    assert body["title"] == "Тестовое событие"
    assert body["product_sku"] == "SKU-TEST-123"
    assert body["task_ids"] == "101,102"
    assert body["user_name"] == "System User"


@pytest.mark.asyncio
async def test_get_audit_logs_pagination_and_filters(client, session) -> None:
    # Очистим логи
    await session.execute(AuditLog.__table__.delete())
    await session.commit()

    # Создадим несколько логов
    for i in range(15):
        log = AuditLog(
            status="success" if i % 2 == 0 else "error",
            title=f"Событие {i}",
            message=f"Сообщение {i}",
            product_sku=f"SKU-{i}",
        )
        session.add(log)
    await session.commit()

    # 1. Проверим лимит
    response = await client.get("/api/audit-logs?limit=5")
    assert response.status_code == 200
    body = response.json()
    assert len(body["items"]) == 5
    assert body["total"] == 15

    # 2. Проверим фильтр по статусу
    response = await client.get("/api/audit-logs?status=error")
    assert response.status_code == 200
    body = response.json()
    assert all(item["status"] == "error" for item in body["items"])
    assert body["total"] == 7 # 15 всего: 0,2,4,6,8,10,12,14 - success (8), остальное error (7)


@pytest.mark.asyncio
async def test_get_audit_logs_task_statuses(client, session) -> None:
    # 1. Создадим тестовую инфраструктуру для задачи
    from app.models.route import ProductionRoute
    section = Section(code="TST", name="Test Section", is_active=True)
    product = Product(sku="SKU-T", name="Test Product", type=ProductType.finished_good)
    session.add(section)
    session.add(product)
    await session.flush()

    route = ProductionRoute(name="Test Route", is_active=True)
    session.add(route)
    await session.flush()

    route_stage = RouteStage(route_id=route.id, section_id=section.id, sequence=10)
    session.add(route_stage)
    await session.flush()

    # Создадим SectionPlanLine
    from app.models.internal_plan import InternalPlan, SectionPlanLine
    from app.models.production_plan import PlanPosition, ProductionPlan, ProductionPlanStatus, PlanPositionStatus, PlanPositionValidationStatus, PlanSourceType
    plan = ProductionPlan(plan_no="PL-T", name="Plan Test")
    session.add(plan)
    await session.flush()

    pos = PlanPosition(
        production_plan_id=plan.id,
        product_id=product.id,
        source_type=PlanSourceType.manual,
        source_sku="SKU-T",
        quantity=10,
        status=PlanPositionStatus.approved,
        validation_status=PlanPositionValidationStatus.valid,
    )
    session.add(pos)
    await session.flush()

    internal_plan = InternalPlan(production_plan_id=plan.id)
    session.add(internal_plan)
    await session.flush()

    line = SectionPlanLine(
        internal_plan_id=internal_plan.id,
        plan_position_id=pos.id,
        section_id=section.id,
        product_id=product.id,
        route_id=route.id,
        route_stage_id=route_stage.id,
        sequence=10,
        planned_quantity=10,
    )
    session.add(line)
    await session.flush()

    task = WorkTask(
        section_plan_line_id=line.id,
        section_id=section.id,
        product_id=product.id,
        route_stage_id=route_stage.id,
        planned_quantity=10,
        status=WorkTaskStatus.ready,
    )
    session.add(task)
    await session.flush()

    # Запишем лог аудита, привязанный к task.id и какому-то несуществующему ID (999)
    log = AuditLog(
        status="success",
        title="Тест задачи",
        message="Проверка статуса",
        task_ids=f"{task.id},999",
    )
    session.add(log)
    await session.commit()

    # 2. Сделаем GET запрос к API логов
    response = await client.get(f"/api/audit-logs?limit=5")
    assert response.status_code == 200
    body = response.json()
    
    # 3. Проверим task_statuses
    task_statuses = body["task_statuses"]
    assert task_statuses[str(task.id)] == "active"
    assert task_statuses["999"] == "deleted"

    # 4. Удалим задачу
    await session.delete(task)
    await session.commit()

    # 5. Снова запросим логи
    response = await client.get(f"/api/audit-logs?limit=5")
    assert response.status_code == 200
    body = response.json()
    
    # 6. Проверим, что теперь задача отображается как deleted
    task_statuses = body["task_statuses"]
    assert task_statuses[str(task.id)] == "deleted"
    assert task_statuses["999"] == "deleted"


@pytest.mark.asyncio
async def test_audit_logs_filter_product_sku_across_pages(client, session) -> None:
    await session.execute(AuditLog.__table__.delete())
    await session.commit()

    session.add(AuditLog(
        status="success",
        title="Target event",
        message="Unique marker",
        product_sku="UNIQUE-AUDIT-SKU-42",
    ))
    await session.flush()
    for i in range(60):
        session.add(AuditLog(
            status="success",
            title=f"Bulk event {i}",
            message=f"Message {i}",
            product_sku=f"BULK-SKU-{i:03d}",
        ))
    await session.commit()

    unfiltered = await client.get("/api/audit-logs?limit=50&offset=0")
    assert unfiltered.status_code == 200
    first_page_skus = {item["product_sku"] for item in unfiltered.json()["items"]}
    assert "UNIQUE-AUDIT-SKU-42" not in first_page_skus

    filtered = await client.get(
        "/api/audit-logs?product_sku=UNIQUE-AUDIT-SKU-42&limit=50&offset=0",
    )
    assert filtered.status_code == 200
    body = filtered.json()
    assert body["total"] == 1
    assert len(body["items"]) == 1
    assert body["items"][0]["product_sku"] == "UNIQUE-AUDIT-SKU-42"


@pytest.mark.asyncio
async def test_audit_logs_sort_by_section_name(client, session) -> None:
    await session.execute(AuditLog.__table__.delete())
    await session.commit()

    for section_name in ("Zebra Section", "Alpha Section", "Mike Section"):
        session.add(AuditLog(
            status="success",
            title=f"Event at {section_name}",
            message="Sort test",
            section_name=section_name,
        ))
    await session.commit()

    response = await client.get(
        "/api/audit-logs?sort_by=section_name&sort_order=asc&limit=50",
    )
    assert response.status_code == 200
    names = [item["section_name"] for item in response.json()["items"]]
    assert names == ["Alpha Section", "Mike Section", "Zebra Section"]
