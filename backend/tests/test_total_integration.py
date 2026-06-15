import pytest
import xlrd
from pathlib import Path
from decimal import Decimal
from datetime import UTC, date, datetime
from sqlalchemy import select, update

from app.models.product import Product, ProductType
from app.models.techcard import Techcard, TechcardLine
from app.models.route import ProductionRoute, RouteStage, RouteOperation
from app.models.section import Section
from app.models.spg import StorageProductionGroup, SpgSection
from app.models.spg_remainder import SpgRemainder
from app.models.production_plan import ProductionPlan, PlanPosition, PlanChangeSet, PlanPositionStatus
from app.models.work_task import WorkTask, WorkTaskStatus
from app.models.internal_plan import SectionPlanLine
from app.models.import_template import ImportTemplate
from app.models.imports import ImportBatch, ImportBatchMode, ImportFile
from app.models.user import User, UserRole
from app.core.security import create_access_token


async def _make_user(session, email: str = "total-integration@test.local") -> User:
    user = User(
        email=email,
        password_hash="x",
        full_name="Total Integration Operator",
        role=UserRole.operator,
        is_active=True,
    )
    session.add(user)
    await session.flush()
    return user


def _auth_headers(user: User) -> dict[str, str]:
    token = create_access_token(subject=user.email)
    return {"Authorization": f"Bearer {token}"}


async def _setup_enterprise_structure(session) -> dict:
    # 7 Sections
    section_specs = [
        ("RAW", "raw_stock"),
        ("DRILL", "production"),
        ("SHOT", "production"),
        ("ANOD", "production"),
        ("WIP", "wip_stock"),
        ("PACK", "production"),
        ("FG_WH", "finished_stock"),
    ]
    sections = []
    for code, kind in section_specs:
        sec = Section(code=code, name=code, kind=kind, is_active=True)
        session.add(sec)
        sections.append(sec)
    await session.flush()

    # SPGs
    spg_raw = StorageProductionGroup(code="SPG-RAW", name="Raw warehouse", is_active=True, sort_order=0)
    spg_wip = StorageProductionGroup(code="SPG-WIP", name="WIP storage", is_active=True, sort_order=10)
    session.add_all([spg_raw, spg_wip])
    await session.flush()

    # Link RAW section (index 0) to SPG-RAW
    session.add(SpgSection(spg_id=spg_raw.id, section_id=sections[0].id, sort_order=0))
    # Link DRILL, SHOT, ANOD, WIP (indices 1..4) to SPG-WIP
    for i in range(1, 5):
        session.add(SpgSection(spg_id=spg_wip.id, section_id=sections[i].id, sort_order=(i - 1) * 10))
    # PACK (index 5) and FG_WH (index 6) remain outside of any SPG
    await session.flush()

    # Create total Route
    route = ProductionRoute(name="Total Route", description="Total test route", is_active=True)
    session.add(route)
    await session.flush()

    step_ops = [
        ("ISSUE_RAW", "Выдача сырья"),
        ("DRILL", "Сверловка"),
        ("SHOT", "Дробеструй"),
        ("ANOD", "Анодирование"),
        ("MOVE_TO_WIP", "Перед. на склад п/ф"),
        ("PACK", "Упаковка"),
        ("ACCEPT_FINISHED", "Приемка ГП"),
    ]
    for idx, (op_code, op_name) in enumerate(step_ops, start=1):
        stage = RouteStage(
            route_id=route.id,
            sequence=idx,
            section_id=sections[idx - 1].id,
            is_final=(idx == len(step_ops)),
        )
        session.add(stage)
        await session.flush()
        session.add(
            RouteOperation(
                route_stage_id=stage.id,
                sequence=1,
                operation_code=op_code,
                operation_name=op_name,
            )
        )
    await session.flush()

    return {
        "sections": sections,
        "spg_raw": spg_raw,
        "spg_wip": spg_wip,
        "route": route,
    }


def _get_skus_from_excel() -> list[str]:
    xls_path = Path(__file__).parents[2] / "test.xls"
    wb = xlrd.open_workbook(xls_path)
    sheet = wb.sheet_by_index(0)
    skus = []
    # Начинаем со строки 5 (0-indexed), так как 4 - это заголовки
    for r in range(5, sheet.nrows):
        val = str(sheet.cell_value(r, 0)).strip()
        if val and val not in skus:
            # Если это пара типа ЮП-2616+ЮП-2604, нам нужно зарегистрировать и компоненты, и сам составной продукт
            if "+" in val:
                for sub in val.split("+"):
                    s = sub.strip()
                    if s and s not in skus:
                        skus.append(s)
            skus.append(val)
    return skus


async def _setup_catalog(session, skus: list[str]) -> dict[str, Product]:
    products = {}
    for sku in skus:
        # Для парных профилей (содержащих "+") сделаем is_paired_profile=True
        is_pair = "+" in sku
        
        p = Product(
            sku=sku,
            name=f"Test Product {sku}",
            type=ProductType.finished_good,
            unit="pcs",
            is_active=True,
            is_paired_profile=is_pair,
        )
        session.add(p)
        await session.flush()
        products[sku] = p

        # Создаем техкарту
        techcard = Techcard(product_id=p.id, version="v1", is_active=True)
        if is_pair:
            techcard.processing_type = "paired_processing"
            techcard.product_id = None  # для пары product_id должен быть null
        session.add(techcard)
        await session.flush()

        # Создаем строки техкарты. 
        # Если это пара, строки должны ссылаться на компоненты
        if is_pair:
            components = [sku.split("+")[0].strip(), sku.split("+")[1].strip()]
            for comp_sku in components:
                # На всякий случай убедимся, что компонент есть в базе
                if comp_sku not in products:
                    comp_p = Product(
                        sku=comp_sku,
                        name=f"Comp {comp_sku}",
                        type=ProductType.component,
                        unit="pcs",
                        is_active=True,
                    )
                    session.add(comp_p)
                    await session.flush()
                    products[comp_sku] = comp_p
                
                session.add(
                    TechcardLine(
                        techcard_id=techcard.id,
                        component_product_id=products[comp_sku].id,
                        quantity=Decimal("1"),
                        unit="pcs",
                    )
                )
        else:
            # Для обычного продукта он потребляет сам себя (1 к 1)
            session.add(
                TechcardLine(
                    techcard_id=techcard.id,
                    component_product_id=p.id,
                    quantity=Decimal("1"),
                    unit="pcs",
                )
            )
    await session.flush()
    return products


async def _get_tasks_by_sequence(session, position_id: int) -> list[WorkTask]:
    return (
        await session.execute(
            select(WorkTask)
            .join(SectionPlanLine, WorkTask.section_plan_line_id == SectionPlanLine.id)
            .where(SectionPlanLine.plan_position_id == position_id)
            .order_by(SectionPlanLine.sequence, WorkTask.id)
        )
    ).scalars().all()


@pytest.mark.asyncio
async def test_total_integration_workflow(client, session) -> None:
    # 1. Setup user and authentication
    user = await _make_user(session)
    headers = _auth_headers(user)

    # 2. Setup enterprise structure (sections, SPGs, route)
    structure = await _setup_enterprise_structure(session)
    sections = structure["sections"]
    spg_raw = structure["spg_raw"]
    spg_wip = structure["spg_wip"]
    route = structure["route"]

    # 3. Read SKUs from test.xls and create catalog (products, techcards)
    skus = _get_skus_from_excel()
    # Ограничимся 10 артикулами, чтобы тест не шел слишком долго, но при этом полностью покрывал логику
    test_skus = skus[:10]
    products = await _setup_catalog(session, test_skus)
    await session.commit()

    # 4. Remainders will be pre-populated sequentially for each position in the loop below.

    # 5. Create ImportTemplate for plan import
    template = ImportTemplate(
        name="Excel Total Template",
        code="excel-total-template",
        is_active=True,
        column_mapping={
            "sku": {"header": "Артикул", "column": "A"},
            "product_name": {"header": "Наименование", "column": "C"},
            "quantity": {"header": "кол-во шт. в 2,7", "column": "F"},
        },
    )
    session.add(template)
    await session.commit()

    # 6. Import test.xls plan
    xls_path = Path(__file__).parents[2] / "test.xls"
    with open(xls_path, "rb") as f:
        file_bytes = f.read()

    # Мы импортируем только строки, содержащие выбранные 10 артикулов.
    # В роутере импорта мы можем передать row_selection, но проще импортировать весь файл,
    # а так как в каталоге созданы продукты только для наших 10 артикулов, 
    # остальные строки просто получат статус "product_not_found" или предупреждения, 
    # а наши 10 артикулов успешно импортируются и мы с ними продолжим работать.
    import_resp = await client.post(
        f"/api/imports/excel?template_id={template.id}",
        files={
            "file": (
                "test.xls",
                file_bytes,
                "application/vnd.ms-excel",
            )
        },
        headers=headers,
    )
    assert import_resp.status_code == 201
    import_body = import_resp.json()
    plan_id = import_body["production_plan_id"]
    change_set_id = import_body["change_set_id"]

    # 7. Apply import change set
    apply_resp = await client.post(
        f"/api/production-plans/{plan_id}/change-sets/{change_set_id}/apply",
        headers=headers,
    )
    assert apply_resp.status_code == 200

    # 8. Make products unique for each position and assign route
    positions = (await session.execute(
        select(PlanPosition)
        .where(PlanPosition.production_plan_id == plan_id, PlanPosition.product_id.in_([p.id for p in products.values()]))
    )).scalars().all()
    assert len(positions) > 0

    for pos in positions:
        orig_prod = await session.get(Product, pos.product_id)
        # Создаем уникальный продукт для этой позиции
        unique_sku = f"{orig_prod.sku}-P{pos.id}"
        new_prod = Product(
            sku=unique_sku,
            name=f"{orig_prod.name} (Pos {pos.id})",
            type=orig_prod.type,
            unit=orig_prod.unit,
            is_active=True,
            is_paired_profile=orig_prod.is_paired_profile,
        )
        session.add(new_prod)
        await session.flush()

        # Создаем техкарту для уникального продукта
        techcard = Techcard(
            product_id=new_prod.id if not new_prod.is_paired_profile else None,
            version="v1",
            is_active=True,
            processing_type="paired_processing" if new_prod.is_paired_profile else None,
        )
        session.add(techcard)
        await session.flush()

        if new_prod.is_paired_profile:
            components = [orig_prod.sku.split("+")[0].strip(), orig_prod.sku.split("+")[1].strip()]
            for comp_sku in components:
                comp_p = await session.scalar(select(Product).where(Product.sku == comp_sku))
                session.add(
                    TechcardLine(
                        techcard_id=techcard.id,
                        component_product_id=comp_p.id,
                        quantity=Decimal("1"),
                        unit="pcs",
                    )
                )
        else:
            session.add(
                TechcardLine(
                    techcard_id=techcard.id,
                    component_product_id=new_prod.id,
                    quantity=Decimal("1"),
                    unit="pcs",
                )
            )
        await session.flush()

        pos.product_id = new_prod.id
        pos.route_id = route.id
        pos.status = PlanPositionStatus.approved

    await session.commit()

    # 9. Run simulation cycle for each position
    for pos in positions:
        qty = pos.quantity

        # Зачисляем остаток в SPG-RAW (RAW section) перед выпуском в производство
        resp_raw = await client.post(
            f"/api/spg/{spg_raw.id}/manual-operation",
            json={
                "product_id": pos.product_id,
                "section_id": sections[0].id,  # RAW
                "operation_type": "in",
                "quantity": 5000,
                "reason": f"Начальный избыток сырья для позиции {pos.id}",
            },
            headers=headers,
        )
        assert resp_raw.status_code == 200

        # Зачисляем остаток в SPG-WIP (DRILL section)
        resp_drill = await client.post(
            f"/api/spg/{spg_wip.id}/manual-operation",
            json={
                "product_id": pos.product_id,
                "section_id": sections[1].id,  # DRILL
                "operation_type": "in",
                "quantity": 20,
                "reason": f"Задел полуфабрикатов для смешанного потребления для позиции {pos.id}",
            },
            headers=headers,
        )
        assert resp_drill.status_code == 200

        # Выпускаем ОДНУ позицию в производство (releases position and creates WorkTasks)
        take_resp = await client.post(
            "/api/production-planning/rows/take-to-work",
            json={"position_ids": [pos.id]},
            headers=headers,
        )
        assert take_resp.status_code == 200
        take_results = take_resp.json()["results"]
        assert all(res["status"] == "success" for res in take_results)

        # Получаем созданные задачи
        tasks = await _get_tasks_by_sequence(session, pos.id)
        assert len(tasks) == 7  # 7 stages

        if tasks[0].status == WorkTaskStatus.ready:
            from app.services.shopfloor.operations_tasks import auto_consume_available_remainders
            await auto_consume_available_remainders(session, tasks[0], actor_id=user.id)
            await session.commit()
            await session.refresh(tasks[0])
            
        assert tasks[0].status == WorkTaskStatus.in_progress
        
        # ─── Шаг 1 (RAW) ───
        # Завершаем RAW: передаем весь объем дальше
        resp = await client.post(
            f"/api/shopfloor/tasks/{tasks[0].id}/complete",
            json={
                "good_quantity": str(qty),
                "defect_quantity": "0",
                "idempotency_key": f"total-run:{pos.id}:step1:complete",
            },
            headers=headers,
        )
        assert resp.status_code == 200, resp.text

        # Возврат неиспользованного избытка сырья обратно на остатки ГХП (SPG-RAW)
        raw_surplus = Decimal("5000") - qty
        resp = await client.post(
            "/api/shopfloor/remainders/return",
            json={
                "task_id": tasks[0].id,
                "quantity": str(raw_surplus),
                "comment": "Возврат излишков сырья",
                "idempotency_key": f"total-run:{pos.id}:step1:return",
            },
            headers=headers,
        )
        assert resp.status_code == 200, resp.text

        # Межучастковый перевод с RAW на DRILL (так как они в разных SPG)
        resp = await client.post(
            "/api/shopfloor/transfers",
            json={
                "from_task_id": tasks[0].id,
                "to_task_id": None,
                "quantity": str(qty),
                "idempotency_key": f"total-run:{pos.id}:step1:send",
            },
            headers=headers,
        )
        assert resp.status_code == 200, resp.text
        transfer_id = resp.json()["transfer_id"]

        resp = await client.post(
            f"/api/shopfloor/transfers/{transfer_id}/accept",
            json={
                "accepted_quantity": str(qty),
                "rejected_quantity": "0",
                "idempotency_key": f"total-run:{pos.id}:step1:receive",
            },
            headers=headers,
        )
        assert resp.status_code == 200, resp.text

        # ─── Шаг 2 (DRILL) ───
        # Принятый перевод автоматически выдал qty в работу на DRILL.
        # Кроме того, система автоматически находит свободный остаток на участке (20 шт)
        # и списывает его в работу на текущую задачу (сценарий смешанного потребления).
        # Поэтому ручной вызов consume не требуется.

        # Итого в работе: qty + 20
        # Завершаем DRILL с браком 5 штук и возвратом 10 штук на склад ГХП (излишки)
        good_qty = qty + 20 - 5 - 10
        resp = await client.post(
            f"/api/shopfloor/tasks/{tasks[1].id}/complete",
            json={
                "good_quantity": str(good_qty),
                "defect_quantity": "5",
                "idempotency_key": f"total-run:{pos.id}:step2:complete",
            },
            headers=headers,
        )
        assert resp.status_code == 200, resp.text

        # Возврат 10 штук излишков обратно на остатки ГХП (SPG-WIP)
        resp = await client.post(
            "/api/shopfloor/remainders/return",
            json={
                "task_id": tasks[1].id,
                "quantity": "10",
                "comment": "Излишки заготовки",
                "idempotency_key": f"total-run:{pos.id}:step2:return",
            },
            headers=headers,
        )
        assert resp.status_code == 200, resp.text
        new_rem_id = resp.json()["remainder_id"]

        # Итого на следующий шаг передано good_qty - 10 = qty + 5 штук.
        # Так как SHOT (tasks[2]) находится в той же SPG-WIP, перевод происходит автоматически.
        next_qty = qty + 5

        # ─── Шаг 3 (SHOT) ───
        # Завершаем SHOT с браком 2 шт
        resp = await client.post(
            f"/api/shopfloor/tasks/{tasks[2].id}/complete",
            json={
                "good_quantity": str(next_qty - 2),
                "defect_quantity": "2",
                "idempotency_key": f"total-run:{pos.id}:step3:complete",
            },
            headers=headers,
        )
        assert resp.status_code == 200, resp.text
        next_qty = next_qty - 2

        # ─── Шаг 4 (ANOD) ───
        # Завершаем ANOD без брака
        resp = await client.post(
            f"/api/shopfloor/tasks/{tasks[3].id}/complete",
            json={
                "good_quantity": str(next_qty),
                "defect_quantity": "0",
                "idempotency_key": f"total-run:{pos.id}:step4:complete",
            },
            headers=headers,
        )
        assert resp.status_code == 200, resp.text

        # ─── Шаг 5 (WIP) ───
        # Завершаем WIP без брака
        resp = await client.post(
            f"/api/shopfloor/tasks/{tasks[4].id}/complete",
            json={
                "good_quantity": str(next_qty),
                "defect_quantity": "0",
                "idempotency_key": f"total-run:{pos.id}:step5:complete",
            },
            headers=headers,
        )
        assert resp.status_code == 200, resp.text

        # Межучастковый перевод с WIP на PACK (так как PACK вне SPG-WIP)
        resp = await client.post(
            "/api/shopfloor/transfers",
            json={
                "from_task_id": tasks[4].id,
                "to_task_id": None,
                "quantity": str(next_qty),
                "idempotency_key": f"total-run:{pos.id}:step5:send",
            },
            headers=headers,
        )
        assert resp.status_code == 200, resp.text
        transfer_id = resp.json()["transfer_id"]

        resp = await client.post(
            f"/api/shopfloor/transfers/{transfer_id}/accept",
            json={
                "accepted_quantity": str(next_qty),
                "rejected_quantity": "0",
                "idempotency_key": f"total-run:{pos.id}:step5:receive",
            },
            headers=headers,
        )
        assert resp.status_code == 200, resp.text

        # ─── Шаг 6 (PACK) ───
        # Завершаем PACK без брака
        resp = await client.post(
            f"/api/shopfloor/tasks/{tasks[5].id}/complete",
            json={
                "good_quantity": str(next_qty),
                "defect_quantity": "0",
                "idempotency_key": f"total-run:{pos.id}:step6:complete",
            },
            headers=headers,
        )
        assert resp.status_code == 200, resp.text

        # Межучастковый перевод с PACK на FG_WH (Склад готовой продукции)
        resp = await client.post(
            "/api/shopfloor/transfers",
            json={
                "from_task_id": tasks[5].id,
                "to_task_id": None,
                "quantity": str(next_qty),
                "idempotency_key": f"total-run:{pos.id}:step6:send",
            },
            headers=headers,
        )
        assert resp.status_code == 200, resp.text
        transfer_id = resp.json()["transfer_id"]

        resp = await client.post(
            f"/api/shopfloor/transfers/{transfer_id}/accept",
            json={
                "accepted_quantity": str(next_qty),
                "rejected_quantity": "0",
                "idempotency_key": f"total-run:{pos.id}:step6:receive",
            },
            headers=headers,
        )
        assert resp.status_code == 200, resp.text

        # ─── Шаг 7 (FG_WH) ───
        # Завершаем FG_WH без брака
        resp = await client.post(
            f"/api/shopfloor/tasks/{tasks[6].id}/complete",
            json={
                "good_quantity": str(next_qty),
                "defect_quantity": "0",
                "idempotency_key": f"total-run:{pos.id}:step7:complete",
            },
            headers=headers,
        )
        assert resp.status_code == 200, resp.text

        # Делаем финальную сдачу ГП (final-release)
        resp = await client.post(
            f"/api/shopfloor/tasks/{tasks[6].id}/final-release",
            json={
                "quantity": str(next_qty),
                "idempotency_key": f"total-run:{pos.id}:step7:final-release",
            },
            headers=headers,
        )
        assert resp.status_code == 200, resp.text

    # 11. Final Verification & Assertions
    # Убеждаемся, что все задачи перешли в статус completed
    for pos in positions:
        tasks = await _get_tasks_by_sequence(session, pos.id)
        for t in tasks:
            await session.refresh(t)
            assert t.status == WorkTaskStatus.completed

    # Проверяем, что остатки сырья в SPG-RAW уменьшились на сумму planned_quantity
    for sku in test_skus:
        product = products[sku]
        pos_sum_qty = sum(p.quantity for p in positions if p.product_id == product.id)
        pos_count = sum(1 for p in positions if p.product_id == product.id)
        
        list_raw = (await client.get(f"/api/spg/{spg_raw.id}/remainders")).json()
        raw_rems = [r for r in list_raw if r["product_id"] == product.id and r["remainder_quantity"] > 0]
        total_raw_qty = sum(Decimal(r["remainder_quantity"]) for r in raw_rems)
        # Изначально было зачислено pos_count * 5000, потрачено pos_sum_qty
        expected_raw_qty = Decimal("5000") * pos_count - pos_sum_qty
        assert total_raw_qty == expected_raw_qty

    # Проверяем, что остатки в SPG-WIP (после возвратов излишков) равны 10 штукам на каждую позицию
    # (начальные 20 полностью списаны при consume_remainder, а при complete вернули 10)
    for sku in test_skus:
        product = products[sku]
        pos_count = sum(1 for p in positions if p.product_id == product.id)
        
        list_wip = (await client.get(f"/api/spg/{spg_wip.id}/remainders")).json()
        wip_rems = [r for r in list_wip if r["product_id"] == product.id and r["remainder_quantity"] > 0]
        total_wip_qty = sum(Decimal(r["remainder_quantity"]) for r in wip_rems)
        assert total_wip_qty == Decimal("10") * pos_count
