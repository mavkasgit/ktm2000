"""Find-or-create SCRAP-секции по объекту канона ScrapPolicy (тикет #132).

Шов ``scrap_policy.find_or_create_scrap_section_id`` — единственный владелец
резолва SCRAP-участка для complete_task и defect_decide. Здесь покрыта ветка
автосоздания: фикстуры БЕЗ предсозданной SCRAP-секции (сид мог не выполняться),
операционный путь сам заводит справочную запись по полям канона; повторные
операции переиспользуют найденную секцию и не плодят дублей.
"""
from __future__ import annotations

from datetime import date
from decimal import Decimal

import pytest
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Product, ProductType, Section, User, UserRole
from app.models.defect import DefectDecisionType
from app.models.internal_plan import InternalPlan, InternalPlanStatus, SectionPlanLine
from app.models.production_plan import (
    PlanPosition,
    PlanPositionStatus,
    PlanPositionValidationStatus,
    PlanSourceType,
    ProductionPlan,
    ProductionPlanStatus,
)
from app.models.route import ProductionRoute, RouteOperation, RouteStage
from app.models.spg import SpgSection, StorageProductionGroup
from app.models.techcard import Techcard, TechcardLine
from app.models.work_task import WorkTask, WorkTaskStatus
from app.seeds.canon.models import ScrapPolicy
from app.stock import Reason, StockCommand, StockCommandService, StockTransaction
from app.services.shopfloor.operations_defects import create_defect, defect_decide
from app.services.shopfloor.operations_tasks import complete_task
from tests.stock.helpers import FAKE_DEFECT_DECISION_MAP, FAKE_SCRAP_POLICY, record_transfer_receive
from tests.test_integrity_invariants import assert_no_invariants_violations

pytestmark = pytest.mark.asyncio


# ─── fixtures ────────────────────────────────────────────────────────────────


async def _make_route_without_scrap(
    session: AsyncSession, *, sku: str = "SCRAP-POL", qty: Decimal = Decimal("10"),
) -> dict:
    """Минимальная топология raw → production, намеренно БЕЗ SCRAP-секции."""
    user = User(
        username=f"{sku}@local",
        email=f"{sku}@local",
        full_name="Scrap Policy Op",
        role=UserRole.operator,
        is_active=True,
    )
    session.add(user)
    await session.flush()

    raw = Section(code=f"{sku}-RAW", name="Raw", type="raw_stock", is_active=True, sort_order=0)
    prod = Section(code=f"{sku}-PROD", name="Production", type="laser", is_active=True, sort_order=1)
    session.add_all([raw, prod])
    await session.flush()

    spg = StorageProductionGroup(code=f"{sku}-SPG", name="SPG", is_active=True, sort_order=0)
    session.add(spg)
    await session.flush()
    session.add(SpgSection(spg_id=spg.id, section_id=prod.id, sort_order=0))

    product = Product(sku=sku, name=sku, type=ProductType.finished_good, unit="pcs", is_active=True)
    session.add(product)
    await session.flush()

    route = ProductionRoute(name=f"R-{sku}", is_active=True)
    session.add(route)
    await session.flush()
    stage = RouteStage(route_id=route.id, sequence=1, section_id=prod.id, is_final=True)
    session.add(stage)
    await session.flush()
    session.add(RouteOperation(route_stage_id=stage.id, sequence=1, operation_code="OP1", operation_name="Op1"))

    tech = Techcard(product_id=product.id, version="v1", is_active=True)
    session.add(tech)
    await session.flush()
    session.add(TechcardLine(techcard_id=tech.id, component_product_id=product.id, quantity=Decimal("1"), unit="pcs"))

    plan = ProductionPlan(
        plan_no=f"P-{sku}", name="p", status=ProductionPlanStatus.approved,
        period_start=date(2026, 6, 1), period_end=date(2026, 6, 30),
    )
    session.add(plan)
    await session.flush()

    pos = PlanPosition(
        production_plan_id=plan.id, product_id=product.id,
        source_type=PlanSourceType.manual, source_sku=product.sku, source_name=product.name,
        quantity=qty, source_payload={}, status=PlanPositionStatus.approved,
        validation_status=PlanPositionValidationStatus.valid, validation_errors=[],
        period_start=plan.period_start, period_end=plan.period_end,
        has_pack_ops=False, route_id=route.id, route_assigned_at=None,
    )
    session.add(pos)
    await session.flush()

    internal_plan = InternalPlan(production_plan_id=plan.id, status=InternalPlanStatus.active)
    session.add(internal_plan)
    await session.flush()

    line = SectionPlanLine(
        internal_plan_id=internal_plan.id,
        plan_position_id=pos.id, section_id=prod.id,
        route_stage_id=stage.id, product_id=product.id,
        route_id=route.id, sequence=1, planned_quantity=qty,
    )
    session.add(line)
    await session.flush()

    task = WorkTask(
        section_plan_line_id=line.id, section_id=prod.id,
        product_id=product.id, route_stage_id=stage.id,
        planned_quantity=qty, status=WorkTaskStatus.ready,
        due_date=plan.period_end,
    )
    session.add(task)
    await session.commit()

    return {"user": user, "product": product, "task": task, "raw": raw, "prod": prod}


async def _issue_material(session: AsyncSession, fx: dict, *, quantity: Decimal) -> None:
    """Выдача материала на участок: MANUAL_IN на raw + TRANSFER_RECEIVE на задачу."""
    svc = StockCommandService()
    await svc.record(session, StockCommand(
        product_id=fx["product"].id,
        from_location_id=None,
        to_location_id=fx["raw"].id,
        quantity=quantity,
        reason=Reason.MANUAL_IN,
        created_by=fx["user"].id,
    ))
    await record_transfer_receive(
        session,
        product_id=fx["product"].id,
        from_location_id=fx["raw"].id,
        to_location_id=fx["task"].section_id,
        quantity=quantity,
        task_id=fx["task"].id,
        created_by=fx["user"].id,
    )
    fx["task"].status = WorkTaskStatus.in_progress
    await session.commit()


async def _scrap_sections(session: AsyncSession) -> list[Section]:
    return (await session.execute(
        select(Section).where(Section.type == ScrapPolicy().section_type).order_by(Section.id)
    )).scalars().all()


async def _scrap_sum_to(session: AsyncSession, location_id: int, task_id: int) -> Decimal:
    return (await session.scalar(
        select(func.coalesce(func.sum(StockTransaction.quantity), 0)).where(
            StockTransaction.task_id == task_id,
            StockTransaction.reason == Reason.SCRAP,
            StockTransaction.to_location_id == location_id,
        )
    )) or Decimal("0")


# ─── tests ──────────────────────────────────────────────────────────────────


async def test_complete_task_auto_creates_scrap_section_from_canon(session: AsyncSession):
    """complete_task с браком при отсутствии SCRAP-секции создаёт её по канону."""
    fx = await _make_route_without_scrap(session, sku="SCRPOL-AUTO")
    assert await _scrap_sections(session) == []

    await _issue_material(session, fx, quantity=Decimal("10"))
    result = await complete_task(
        session,
        task_id=fx["task"].id,
        good_quantity=Decimal("7"),
        defect_quantity=Decimal("3"),
        actor_id=fx["user"].id,
        defect_reason="test_scrap",
        **FAKE_SCRAP_POLICY,
    )
    await session.commit()

    policy = ScrapPolicy()
    sections = await _scrap_sections(session)
    assert len(sections) == 1, "SCRAP-секция должна быть создана ровно одна"
    created = sections[0]
    assert created.code == policy.code
    assert created.name == policy.name
    assert created.type == policy.section_type
    assert created.sort_order == policy.sort_order

    # SCRAP-проводка ушла на созданную швом секцию.
    assert result["defect_id"] is not None
    assert await _scrap_sum_to(session, created.id, fx["task"].id) == Decimal("3")

    await assert_no_invariants_violations(session, context="scrap-policy-autocreate")


async def test_repeated_completion_reuses_created_scrap_section(session: AsyncSession):
    """Повторная операция с браком переиспользует найденную секцию (ветка find)."""
    fx = await _make_route_without_scrap(session, sku="SCRPOL-REUSE")
    await _issue_material(session, fx, quantity=Decimal("12"))

    # Порция 1: 8 годных + 2 брака; порция 2 укладывается в остаток выдачи.
    await complete_task(
        session,
        task_id=fx["task"].id,
        good_quantity=Decimal("8"),
        defect_quantity=Decimal("2"),
        actor_id=fx["user"].id,
        **FAKE_SCRAP_POLICY,
    )
    await complete_task(
        session,
        task_id=fx["task"].id,
        good_quantity=Decimal("1"),
        defect_quantity=Decimal("1"),
        actor_id=fx["user"].id,
        **FAKE_SCRAP_POLICY,
    )
    await session.commit()

    sections = await _scrap_sections(session)
    assert len(sections) == 1, "Дубль SCRAP-секции недопустим"
    assert await _scrap_sum_to(session, sections[0].id, fx["task"].id) == Decimal("3")

    await assert_no_invariants_violations(session, context="scrap-policy-reuse")


async def test_defect_decide_scrap_auto_creates_section(session: AsyncSession):
    """defect_decide(scrap) использует тот же шов: секция создаётся по канону."""
    fx = await _make_route_without_scrap(session, sku="SCRPOL-DEC")
    assert await _scrap_sections(session) == []

    # Физический материал на участке под списание брака.
    svc = StockCommandService()
    await svc.record(session, StockCommand(
        product_id=fx["product"].id,
        from_location_id=None,
        to_location_id=fx["prod"].id,
        quantity=Decimal("2"),
        reason=Reason.MANUAL_IN,
        created_by=fx["user"].id,
    ))
    await session.commit()

    defect = await create_defect(
        session,
        product_id=fx["product"].id,
        section_id=fx["prod"].id,
        quantity=Decimal("2"),
        actor_id=fx["user"].id,
        reason="manual_defect",
    )
    decision = await defect_decide(
        session,
        defect_id=defect["defect_id"],
        decision_type=DefectDecisionType.scrap,
        quantity=Decimal("2"),
        actor_id=fx["user"].id,
        defect_decision_map=FAKE_DEFECT_DECISION_MAP,
        **FAKE_SCRAP_POLICY,
    )
    await session.commit()

    policy = ScrapPolicy()
    sections = await _scrap_sections(session)
    assert len(sections) == 1
    assert sections[0].code == policy.code
    assert decision["defect_status"] == FAKE_DEFECT_DECISION_MAP["scrap"].status

    await assert_no_invariants_violations(session, context="scrap-policy-decide")


async def test_complete_task_requires_scrap_policy(session: AsyncSession):
    """Брак без политики отклоняется: данные обязаны прийти из composition root."""
    fx = await _make_route_without_scrap(session, sku="SCRPOL-NONE")
    await _issue_material(session, fx, quantity=Decimal("10"))

    with pytest.raises(ValueError, match="scrap policy data"):
        await complete_task(
            session,
            task_id=fx["task"].id,
            good_quantity=Decimal("7"),
            defect_quantity=Decimal("3"),
            actor_id=fx["user"].id,
            scrap_policy=None,
        )

    # Ни проводки брака, ни записи в справочнике не появилось.
    assert await _scrap_sections(session) == []
    assert await _scrap_sum_to(session, 0, fx["task"].id) == Decimal("0")
