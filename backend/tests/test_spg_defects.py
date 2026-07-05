from decimal import Decimal
import pytest
from sqlalchemy import select

from app.models.product import Product, ProductType
from app.models.section import Section
from app.models.spg import StorageProductionGroup
from app.models.route import ProductionRoute, RouteStage, RouteOperation, RouteRuleProfile
from app.models.defect import Defect, DefectItem, DefectStatus, DefectDecisionType
from app.models.user import User, UserRole
from app.stock import Reason, StockCommand, StockCommandService, StockTransaction


async def _make_admin(session, email: str = "admin-def@test.local") -> User:
    user = User(
        email=email,
        password_hash="x",
        full_name="Defect Admin",
        role=UserRole.admin,
        is_active=True,
    )
    session.add(user)
    await session.flush()
    return user


async def _make_product(session, sku: str) -> Product:
    product = Product(
        sku=sku,
        name=f"Product {sku}",
        type=ProductType.component,
        unit="pcs",
        profile_type="universal",
    )
    session.add(product)
    await session.flush()
    return product


async def _seed_section_good_stock(
    session,
    *,
    product_id: int,
    section_id: int,
    quantity: Decimal | int,
    created_by: int,
) -> None:
    """Seed GOOD stock at a section so scrap decisions can debit from_location."""
    svc = StockCommandService()
    await svc.record(session, StockCommand(
        product_id=product_id,
        from_location_id=None,
        to_location_id=section_id,
        quantity=Decimal(str(quantity)),
        reason=Reason.MANUAL_IN,
        created_by=created_by,
    ))


async def _setup_route_with_stages(session) -> ProductionRoute:
    # 1. Create RouteRuleProfile
    profile = RouteRuleProfile(
        code="packaging_map_rp",
        name="Упаковочная карта РП",
        is_active=True,
        priority=1000,
        route_sections=["DRILLING", "SAWING", "SHIPPED"],
    )
    session.add(profile)
    await session.flush()

    # 2. Create ProductionRoute
    route = ProductionRoute(
        code="dynamic_packaging_map_rp",
        name="Dynamic: Упаковочная карта РП",
        is_active=True,
        sort_order=1000,
    )
    session.add(route)
    await session.flush()

    # 3. Create stages and operations
    sec_drill = Section(code="DRILLING", name="Сверловка", is_active=True)
    sec_saw = Section(code="SAWING", name="Резка", is_active=True)
    sec_sent = Section(code="SHIPPED", name="Отправлено", is_active=True)
    session.add(sec_drill)
    session.add(sec_saw)
    session.add(sec_sent)
    await session.flush()

    # Stage 1: DRILL
    stage1 = RouteStage(route_id=route.id, sequence=1, section_id=sec_drill.id)
    session.add(stage1)
    await session.flush()
    op1 = RouteOperation(route_stage_id=stage1.id, sequence=1, operation_code="DRILL_OP", operation_name="Сверление отверстий")
    session.add(op1)

    # Stage 2: SAW
    stage2 = RouteStage(route_id=route.id, sequence=2, section_id=sec_saw.id)
    session.add(stage2)
    await session.flush()
    op2 = RouteOperation(route_stage_id=stage2.id, sequence=1, operation_code="SAW_OP", operation_name="Поперечный распил")
    session.add(op2)

    await session.flush()
    return route


@pytest.mark.asyncio
async def test_get_product_route_stages(client, session):
    await _make_admin(session)
    product = await _make_product(session, "FG-STAGES-TEST")
    await _setup_route_with_stages(session)

    resp = await client.get(f"/api/products/{product.id}/route-stages")
    assert resp.status_code == 200, resp.text
    data = resp.json()
    assert len(data) == 2
    assert data[0]["section_code"] == "DRILLING"
    assert data[0]["operations"][0]["operation_code"] == "DRILL_OP"
    assert data[1]["section_code"] == "SAWING"
    assert data[1]["operations"][0]["operation_code"] == "SAW_OP"


@pytest.mark.asyncio
async def test_get_product_last_completed_operation(client, session):
    """Test last completed operation via StockTransaction."""
    from app.models.work_task import WorkTask, WorkTaskStatus
    from app.models.internal_plan import SectionPlanLine, InternalPlan
    from app.models.production_plan import (
        ProductionPlan,
        PlanPosition,
        PlanSourceType,
        PlanPositionStatus,
        PlanPositionValidationStatus,
    )
    from app.models.route import SectionOperation
    from datetime import datetime, date

    admin = await _make_admin(session)
    product = await _make_product(session, "FG-LAST-OP-TEST")
    route = await _setup_route_with_stages(session)
    
    # 1. No operations completed yet
    resp = await client.get(f"/api/products/{product.id}/last-completed-operation")
    assert resp.status_code == 200
    data = resp.json()
    assert data.get("section_id") is None

    # 2. Complete an operation via StockTransaction
    sec_drill = await session.scalar(select(Section).where(Section.code == "DRILLING"))
    stage1 = await session.scalar(select(RouteStage).where(RouteStage.route_id == route.id, RouteStage.sequence == 1))

    plan = ProductionPlan(plan_no="PLAN-TEST-OP", name="Test Plan", period_start=date(2026, 6, 1), period_end=date(2026, 6, 30))
    session.add(plan)
    await session.flush()

    int_plan = InternalPlan(production_plan_id=plan.id)
    session.add(int_plan)
    await session.flush()

    pos = PlanPosition(
        production_plan_id=plan.id,
        product_id=product.id,
        source_type=PlanSourceType.manual,
        source_sku=product.sku,
        source_name=product.name,
        quantity=Decimal("100"),
        source_payload={},
        status=PlanPositionStatus.approved,
        validation_status=PlanPositionValidationStatus.valid,
        validation_errors=[],
        period_start=plan.period_start,
        period_end=plan.period_end,
        has_pack_ops=False,
    )
    session.add(pos)
    await session.flush()

    line = SectionPlanLine(
        internal_plan_id=int_plan.id,
        plan_position_id=pos.id,
        section_id=sec_drill.id,
        product_id=product.id,
        route_id=route.id,
        route_stage_id=stage1.id,
        sequence=1,
        planned_quantity=Decimal("100"),
    )
    session.add(line)
    await session.flush()

    task = WorkTask(
        section_plan_line_id=line.id,
        section_id=sec_drill.id,
        product_id=product.id,
        route_stage_id=stage1.id,
        planned_quantity=Decimal("100"),
        status=WorkTaskStatus.completed,
        selected_operation_code="DRILL_OP",
    )
    session.add(task)
    await session.flush()

    # SectionOperation справочник
    sec_op = SectionOperation(
        section_id=sec_drill.id,
        operation_code="DRILL_OP",
        operation_name="Сверление отверстий",
        is_significant=True,
    )
    session.add(sec_op)
    await session.flush()

    # Complete via StockCommandService
    svc = StockCommandService()
    await svc.record(session, StockCommand(
        product_id=product.id, task_id=task.id,
        from_location_id=None, to_location_id=sec_drill.id,
        quantity=Decimal("100"), reason=Reason.COMPLETE,
        created_by=admin.id,
    ))
    await session.commit()

    resp = await client.get(f"/api/products/{product.id}/last-completed-operation")
    assert resp.status_code == 200, resp.text
    data = resp.json()
    assert data.get("section_id") == sec_drill.id
    assert data.get("operation_code") == "DRILL_OP"


@pytest.mark.asyncio
# test_import_remainders_excel removed in Stage 7 — remainders endpoint deleted.


@pytest.mark.asyncio
async def test_manual_defect_registration_and_scrap_decision(client, session):
    admin = await _make_admin(session)
    product = await _make_product(session, "FG-DEFECT-TEST")
    route = await _setup_route_with_stages(session)
    
    drill_sec = await session.scalar(select(Section).where(Section.code == "DRILLING"))
    stage = await session.scalar(select(RouteStage).where(RouteStage.route_id == route.id).limit(1))

    await _seed_section_good_stock(
        session,
        product_id=product.id,
        section_id=drill_sec.id,
        quantity=10,
        created_by=admin.id,
    )

    # Register defect manually
    resp = await client.post(
        "/api/shopfloor/defects",
        json={
            "product_id": product.id,
            "section_id": drill_sec.id,
            "route_stage_id": stage.id,
            "quantity": 10,
            "reason": "Царапины",
            "comment": "Вручную обнаружено"
        }
    )
    assert resp.status_code == 200, resp.text
    defect_id = resp.json()["defect_id"]

    # Verify defect was created
    defect = await session.scalar(select(Defect).where(Defect.id == defect_id))
    assert defect is not None
    assert defect.task_id is None
    assert defect.route_stage_id == stage.id

    # Decide scrap decision on this defect
    dec_resp = await client.post(
        f"/api/shopfloor/defects/{defect_id}/decisions",
        json={
            "decision_type": DefectDecisionType.scrap.value,
            "quantity": 10,
            "comment": "Списание брака"
        }
    )
    assert dec_resp.status_code == 200, dec_resp.text
    data = dec_resp.json()
    assert data["defect_status"] == DefectStatus.scrapped.value

    # Verify defect has stock_transaction_id set
    await session.refresh(defect)
    assert defect.stock_transaction_id is not None
    assert defect.status == DefectStatus.scrapped

    # Verify StockTransaction(SCRAP) was created
    tx = await session.get(StockTransaction, defect.stock_transaction_id)
    assert tx is not None
    assert tx.reason == Reason.SCRAP


@pytest.mark.asyncio
async def test_manual_defect_invalid_rework_decision(client, session):
    await _make_admin(session, "defect-invalid-rework@test.local")
    product = await _make_product(session, "FG-REWORK-ERR")
    await _setup_route_with_stages(session)
    
    spg = StorageProductionGroup(code="WIP_ERR", name="WIP SPG ERR")
    session.add(spg)
    await session.flush()

    drill_sec = await session.scalar(select(Section).where(Section.code == "DRILLING"))
    stage = await session.scalar(select(RouteStage).limit(1))

    # 1. Register defect manually (no task_id)
    resp = await client.post(
        "/api/shopfloor/defects",
        json={
            "product_id": product.id,
            "section_id": drill_sec.id,
            "route_stage_id": stage.id,
            "quantity": 5,
            "reason": "scratches",
            "comment": "manual defect"
        }
    )
    assert resp.status_code == 200, resp.text
    defect_id = resp.json()["defect_id"]

    # 2. Try to decide rework_current (which should fail with 400 Bad Request)
    dec_resp = await client.post(
        f"/api/shopfloor/defects/{defect_id}/decisions",
        json={
            "decision_type": "rework_current",
            "quantity": 5,
            "comment": "rework manual defect"
        }
    )
    assert dec_resp.status_code == 400, dec_resp.text
    assert "Rework decisions require an associated work task" in dec_resp.json()["detail"]


@pytest.mark.asyncio
async def test_manual_defect_invalid_stage_or_remainder(client, session):
    await _make_admin(session, "defect-invalid-refs@test.local")
    product = await _make_product(session, "FG-INVALID-REFS")
    drill_sec = Section(code="DRILL_X", name="Сверловка X", is_active=True)
    session.add(drill_sec)
    await session.flush()

    # Test nonexistent route stage
    resp2 = await client.post(
        "/api/shopfloor/defects",
        json={
            "product_id": product.id,
            "section_id": drill_sec.id,
            "route_stage_id": 99999,
            "quantity": 5,
        }
    )
    assert resp2.status_code == 400, resp2.text
    assert "RouteStage 99999 not found" in resp2.json()["detail"]


@pytest.mark.asyncio
async def test_manual_defect_scrap_exceeding_quantity(client, session):
    """Scrap decision создаёт StockTransaction(SCRAP) независимо от количества."""
    admin = await _make_admin(session, "defect-exceed-scrap@test.local")
    product = await _make_product(session, "FG-EXCEED-TEST")
    await _setup_route_with_stages(session)

    drill_sec = await session.scalar(select(Section).where(Section.code == "DRILLING"))
    stage = await session.scalar(select(RouteStage).limit(1))

    await _seed_section_good_stock(
        session,
        product_id=product.id,
        section_id=drill_sec.id,
        quantity=20,
        created_by=admin.id,
    )

    # Register defect
    resp = await client.post(
        "/api/shopfloor/defects",
        json={
            "product_id": product.id,
            "section_id": drill_sec.id,
            "route_stage_id": stage.id,
            "quantity": 20,
            "reason": "scratches",
            "comment": "manual defect"
        }
    )
    assert resp.status_code == 200, resp.text
    defect_id = resp.json()["defect_id"]

    # Decide scrap for 20
    dec_resp = await client.post(
        f"/api/shopfloor/defects/{defect_id}/decisions",
        json={
            "decision_type": DefectDecisionType.scrap.value,
            "quantity": 20,
            "comment": "Списание брака"
        }
    )
    assert dec_resp.status_code == 200, dec_resp.text
    data = dec_resp.json()
    assert data["defect_status"] == DefectStatus.scrapped.value

    # Verify defect has stock_transaction_id set
    defect = await session.scalar(select(Defect).where(Defect.id == defect_id))
    assert defect is not None
    assert defect.stock_transaction_id is not None
    assert defect.status == DefectStatus.scrapped

    # Verify StockTransaction(SCRAP) was created
    tx = await session.get(StockTransaction, defect.stock_transaction_id)
    assert tx is not None
    assert tx.reason == Reason.SCRAP
    assert tx.quantity == Decimal("20")



