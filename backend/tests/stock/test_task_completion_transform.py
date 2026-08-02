"""Завершение задания с трансформацией габаритов (ADR-0002, тикет #8/07.md).

Порция факта на трансформирующем этапе атомарно двигает ledger:
- списание входа: N шт × входной габарит (Reason.TRANSFORM_CONSUME);
- приход всех выходов спецификации: N шт × выходной габарит каждого
  выхода (Reason.COMPLETE с dimensions) — годный остаток приходуется
  автоматически как обычный выход;
- брак пишется SCRAP с габаритом входа;
- частичное выполнение двигает ledger пропорционально порции.

Сценарий тикета: 100 × 2,7 м → 100 × 0,9 м + 100 × 1,8 м,
полный и частичный (50 из 100).
"""
from __future__ import annotations

from datetime import date
from decimal import Decimal

import pytest
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Product, ProductType, Section, User, UserRole
from app.models.defect import Defect
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
from app.services.shopfloor.operations_tasks import complete_task
from app.stock import (
    QualityState,
    Reason,
    StockBalance,
    StockCommand,
    StockCommandService,
    StockTransaction,
    StockValidationError,
)
from app.stock.services import StockProjectionManager, dimensions_match_clause
from tests.test_integrity_invariants import (
    assert_no_stock_ledger_invariants_violations,
)

pytestmark = pytest.mark.asyncio

DIMS_IN = {"length_mm": 2700}
DIMS_OUT_A = {"length_mm": 900}
DIMS_OUT_B = {"length_mm": 1800}

TICKET_OUTPUTS = [
    {"row_number": 1, "quantity": "100", "dimensions": DIMS_OUT_A},
    {"row_number": 2, "quantity": "100", "dimensions": DIMS_OUT_B},
]


# ─── fixtures ────────────────────────────────────────────────────────────────


async def _make_transform_setup(
    session: AsyncSession,
    *,
    sku: str,
    planned_quantity: Decimal = Decimal("200"),
    input_quantity: Decimal = Decimal("100"),
    input_dimensions: dict | None = None,
    outputs: list[dict] | None = None,
) -> dict:
    """Минимальная топология: raw_stock → трансформирующий участок (пила).

    Этап помечен ``transforms_dimensions=True`` (эквивалент сида),
    задание несёт вход и выходы позиции (ADR-0002).
    """
    if input_dimensions is None:
        input_dimensions = dict(DIMS_IN)
    if outputs is None:
        outputs = [dict(entry) for entry in TICKET_OUTPUTS]

    user = User(
        username=f"{sku}-op",
        email=f"{sku}-op@local",
        full_name="Saw Operator",
        role=UserRole.operator,
        is_active=True,
    )
    session.add(user)

    raw = Section(code=f"{sku}-RAW", name="Raw", type="raw_stock", is_active=True, sort_order=0)
    saw = Section(code=f"{sku}-SAW", name="Saw", type="production", is_active=True, sort_order=1)
    scrap = Section(code=f"{sku}-SCR", name="Scrap", type="scrap", is_active=True, sort_order=2)
    session.add_all([raw, saw, scrap])
    await session.flush()

    spg = StorageProductionGroup(code=f"{sku}-SPG", name="SPG", is_active=True, sort_order=0)
    session.add(spg)
    await session.flush()
    session.add(SpgSection(spg_id=spg.id, section_id=saw.id, sort_order=0))

    product = Product(sku=sku, name=sku, type=ProductType.finished_good, unit="pcs", is_active=True)
    session.add(product)
    await session.flush()

    route = ProductionRoute(name=f"R-{sku}", is_active=True)
    session.add(route)
    await session.flush()
    stage = RouteStage(
        route_id=route.id,
        sequence=1,
        section_id=saw.id,
        is_final=True,
        transforms_dimensions=True,
    )
    session.add(stage)
    await session.flush()
    session.add(RouteOperation(route_stage_id=stage.id, sequence=1, operation_code="SAW", operation_name="Saw"))

    tech = Techcard(product_id=product.id, version="v1", is_active=True)
    session.add(tech)
    await session.flush()
    session.add(TechcardLine(techcard_id=tech.id, component_product_id=product.id, quantity=Decimal("1"), unit="pcs"))

    plan = ProductionPlan(
        plan_no=f"P-{sku}", name="p", status=ProductionPlanStatus.approved,
        period_start=date(2026, 7, 1), period_end=date(2026, 7, 31),
    )
    session.add(plan)
    await session.flush()

    pos = PlanPosition(
        production_plan_id=plan.id, product_id=product.id,
        source_type=PlanSourceType.manual, source_sku=product.sku, source_name=product.name,
        quantity=planned_quantity,
        input_quantity=input_quantity,
        input_dimensions=input_dimensions,
        outputs=outputs,
        source_payload={}, status=PlanPositionStatus.approved,
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
        plan_position_id=pos.id, section_id=saw.id,
        route_stage_id=stage.id, product_id=product.id,
        route_id=route.id, sequence=1, planned_quantity=planned_quantity,
    )
    session.add(line)
    await session.flush()

    task = WorkTask(
        section_plan_line_id=line.id, section_id=saw.id,
        product_id=product.id, route_stage_id=stage.id,
        planned_quantity=planned_quantity, status=WorkTaskStatus.ready,
        due_date=plan.period_end,
        input_quantity=input_quantity,
        input_dimensions=input_dimensions,
        outputs=outputs,
    )
    session.add(task)
    await session.commit()

    return {
        "user": user, "product": product, "task": task,
        "raw": raw, "saw": saw, "scrap": scrap, "stage": stage,
    }


async def _receive_input(
    session: AsyncSession,
    fx: dict,
    *,
    quantity: Decimal = Decimal("100"),
    dims: dict | None = DIMS_IN,
) -> None:
    """Приход входа на пилу: MANUAL_IN на raw + TRANSFER_RECEIVE на участок."""
    svc = StockCommandService()
    await svc.record(session, StockCommand(
        product_id=fx["product"].id,
        to_location_id=fx["raw"].id,
        quantity=quantity,
        reason=Reason.MANUAL_IN,
        dimensions=dims,
        created_by=fx["user"].id,
    ))
    await svc.record(session, StockCommand(
        product_id=fx["product"].id,
        from_location_id=fx["raw"].id,
        to_location_id=fx["task"].section_id,
        quantity=quantity,
        reason=Reason.TRANSFER_RECEIVE,
        dimensions=dims,
        task_id=fx["task"].id,
        created_by=fx["user"].id,
    ))
    fx["task"].status = WorkTaskStatus.in_progress
    await session.commit()


async def _balance(
    session: AsyncSession,
    product_id: int,
    location_id: int,
    dims: dict | None,
    quality_state: QualityState = QualityState.GOOD,
) -> Decimal:
    row = await session.execute(
        select(StockBalance).where(
            StockBalance.product_id == product_id,
            StockBalance.location_id == location_id,
            StockBalance.quality_state == quality_state,
            dimensions_match_clause(StockBalance.dimensions, dims),
        )
    )
    bal = row.scalar_one_or_none()
    return bal.balance_qty if bal else Decimal("0")


async def _tx_sum(
    session: AsyncSession,
    task_id: int,
    reason: Reason,
    dims: dict | None = None,
    *,
    any_dims: bool = False,
) -> Decimal:
    stmt = select(func.coalesce(func.sum(StockTransaction.quantity), 0)).where(
        StockTransaction.task_id == task_id,
        StockTransaction.reason == reason,
    )
    if not any_dims:
        stmt = stmt.where(dimensions_match_clause(StockTransaction.dimensions, dims))
    return await session.scalar(stmt) or Decimal("0")


# ─── полный сценарий тикета: 100 × 2,7 → 100 × 0,9 + 100 × 1,8 ──────────────


async def test_full_portion_moves_input_and_all_outputs(session: AsyncSession) -> None:
    """Полная порция: вход списан, все выходы (включая годный остаток 1,8 м)
    оприходованы в одной транзакции БД."""
    fx = await _make_transform_setup(session, sku="TRC-FULL")
    await _receive_input(session, fx)

    result = await complete_task(
        session,
        task_id=fx["task"].id,
        good_quantity=Decimal("100"),
        defect_quantity=Decimal("0"),
        actor_id=fx["user"].id,
    )
    await session.commit()

    # Списание входа: 100 × 2,7 м.
    assert await _tx_sum(session, fx["task"].id, Reason.TRANSFORM_CONSUME, DIMS_IN) == Decimal("100")
    # Приход обоих выходов: 100 × 0,9 м + 100 × 1,8 м (остаток — автоматически).
    assert await _tx_sum(session, fx["task"].id, Reason.COMPLETE, DIMS_OUT_A) == Decimal("100")
    assert await _tx_sum(session, fx["task"].id, Reason.COMPLETE, DIMS_OUT_B) == Decimal("100")
    # 3 транзакции одной порции: consume + 2 выхода.
    assert len(result["transaction_ids"]) == 3

    # Балансы по габаритным группам на пиле.
    product_id, saw_id = fx["product"].id, fx["saw"].id
    assert await _balance(session, product_id, saw_id, DIMS_IN) == Decimal("0")
    assert await _balance(session, product_id, saw_id, DIMS_OUT_A) == Decimal("100")
    assert await _balance(session, product_id, saw_id, DIMS_OUT_B) == Decimal("100")

    # Проекция задачи: completed = сумма выходов.
    cache = await StockProjectionManager().get_task_cache(session, fx["task"].id)
    assert cache["completed_quantity"] == Decimal("200")
    assert cache["issued_quantity"] == Decimal("100")

    await assert_no_stock_ledger_invariants_violations(session, context="transform-full")


async def test_partial_portion_moves_ledger_proportionally(session: AsyncSession) -> None:
    """50 из 100: ledger двигается пропорционально; вторая порция довершает."""
    fx = await _make_transform_setup(session, sku="TRC-PART")
    await _receive_input(session, fx)

    await complete_task(
        session,
        task_id=fx["task"].id,
        good_quantity=Decimal("50"),
        defect_quantity=Decimal("0"),
        actor_id=fx["user"].id,
    )
    await session.commit()

    product_id, saw_id = fx["product"].id, fx["saw"].id
    assert await _tx_sum(session, fx["task"].id, Reason.TRANSFORM_CONSUME, DIMS_IN) == Decimal("50")
    assert await _balance(session, product_id, saw_id, DIMS_IN) == Decimal("50")
    assert await _balance(session, product_id, saw_id, DIMS_OUT_A) == Decimal("50")
    assert await _balance(session, product_id, saw_id, DIMS_OUT_B) == Decimal("50")

    task = await session.get(WorkTask, fx["task"].id)
    assert task.status == WorkTaskStatus.partially_completed
    await assert_no_stock_ledger_invariants_violations(session, context="transform-partial-1")

    # Вторая порция довершает операцию до полной спецификации.
    await complete_task(
        session,
        task_id=fx["task"].id,
        good_quantity=Decimal("50"),
        defect_quantity=Decimal("0"),
        actor_id=fx["user"].id,
    )
    await session.commit()

    assert await _tx_sum(session, fx["task"].id, Reason.TRANSFORM_CONSUME, DIMS_IN) == Decimal("100")
    assert await _balance(session, product_id, saw_id, DIMS_IN) == Decimal("0")
    assert await _balance(session, product_id, saw_id, DIMS_OUT_A) == Decimal("100")
    assert await _balance(session, product_id, saw_id, DIMS_OUT_B) == Decimal("100")

    cache = await StockProjectionManager().get_task_cache(session, fx["task"].id)
    assert cache["completed_quantity"] == Decimal("200")
    await assert_no_stock_ledger_invariants_violations(session, context="transform-partial-2")


async def test_defect_written_with_input_dimensions(session: AsyncSession) -> None:
    """Брак заготовок пишется SCRAP с габаритом входа; выходы — по годным."""
    fx = await _make_transform_setup(session, sku="TRC-DEF")
    await _receive_input(session, fx)

    result = await complete_task(
        session,
        task_id=fx["task"].id,
        good_quantity=Decimal("90"),
        defect_quantity=Decimal("10"),
        actor_id=fx["user"].id,
        defect_reason="saw_jam",
    )
    await session.commit()

    product_id, saw_id = fx["product"].id, fx["saw"].id
    # Списание входа только по годным; брак ушёл SCRAP с габаритом входа.
    assert await _tx_sum(session, fx["task"].id, Reason.TRANSFORM_CONSUME, DIMS_IN) == Decimal("90")
    assert await _tx_sum(session, fx["task"].id, Reason.SCRAP, DIMS_IN) == Decimal("10")
    # Выходы пропорциональны годным: 90 × 0,9 + 90 × 1,8.
    assert await _tx_sum(session, fx["task"].id, Reason.COMPLETE, DIMS_OUT_A) == Decimal("90")
    assert await _tx_sum(session, fx["task"].id, Reason.COMPLETE, DIMS_OUT_B) == Decimal("90")

    assert await _balance(session, product_id, saw_id, DIMS_IN) == Decimal("0")
    assert await _balance(
        session, product_id, fx["scrap"].id, DIMS_IN, QualityState.SCRAP,
    ) == Decimal("10")

    assert result["defect_id"] is not None
    defect = await session.get(Defect, result["defect_id"])
    assert defect is not None

    await assert_no_stock_ledger_invariants_violations(session, context="transform-defect")


async def test_non_one_to_one_outputs_scale_by_input_ratio(session: AsyncSession) -> None:
    """Из 1 заготовки — 3 куска: выходы масштабируются долей входа."""
    fx = await _make_transform_setup(
        session,
        sku="TRC-RATIO",
        planned_quantity=Decimal("300"),
        outputs=[{"row_number": 1, "quantity": "300", "dimensions": DIMS_OUT_A}],
    )
    await _receive_input(session, fx)

    await complete_task(
        session,
        task_id=fx["task"].id,
        good_quantity=Decimal("33"),
        defect_quantity=Decimal("0"),
        actor_id=fx["user"].id,
    )
    await session.commit()
    assert await _tx_sum(session, fx["task"].id, Reason.COMPLETE, DIMS_OUT_A) == Decimal("99")

    # Довершение: суммы сходятся точно к спецификации, без хвостов округления.
    await complete_task(
        session,
        task_id=fx["task"].id,
        good_quantity=Decimal("67"),
        defect_quantity=Decimal("0"),
        actor_id=fx["user"].id,
    )
    await session.commit()
    assert await _tx_sum(session, fx["task"].id, Reason.COMPLETE, DIMS_OUT_A) == Decimal("300")
    assert await _balance(session, fx["product"].id, fx["saw"].id, DIMS_OUT_A) == Decimal("300")
    await assert_no_stock_ledger_invariants_violations(session, context="transform-ratio")


# ─── защита и идемпотентность ────────────────────────────────────────────────


async def test_portion_over_remaining_input_rejected(session: AsyncSession) -> None:
    """Порция больше остатка входа задания отклоняется без записей."""
    fx = await _make_transform_setup(session, sku="TRC-OVER")
    await _receive_input(session, fx)

    with pytest.raises(ValueError, match="remaining input"):
        await complete_task(
            session,
            task_id=fx["task"].id,
            good_quantity=Decimal("150"),
            defect_quantity=Decimal("0"),
            actor_id=fx["user"].id,
        )

    assert await _tx_sum(
        session, fx["task"].id, Reason.TRANSFORM_CONSUME, any_dims=True,
    ) == Decimal("0")
    assert await _tx_sum(
        session, fx["task"].id, Reason.COMPLETE, any_dims=True,
    ) == Decimal("0")


async def test_portion_over_physical_balance_writes_nothing(session: AsyncSession) -> None:
    """Не хватает физического остатка входной группы — атомарный отказ,
    ledger без частичных записей."""
    fx = await _make_transform_setup(session, sku="TRC-PHYS")
    await _receive_input(session, fx, quantity=Decimal("50"))

    with pytest.raises(StockValidationError, match="Insufficient stock"):
        await complete_task(
            session,
            task_id=fx["task"].id,
            good_quantity=Decimal("80"),
            defect_quantity=Decimal("0"),
            actor_id=fx["user"].id,
        )

    assert await _tx_sum(
        session, fx["task"].id, Reason.TRANSFORM_CONSUME, any_dims=True,
    ) == Decimal("0")
    assert await _tx_sum(
        session, fx["task"].id, Reason.COMPLETE, any_dims=True,
    ) == Decimal("0")
    await assert_no_stock_ledger_invariants_violations(session, context="transform-phys")


async def test_idempotent_replay_does_not_duplicate_ledger(session: AsyncSession) -> None:
    """Повтор с тем же idempotency_key не дублирует движения ledger."""
    fx = await _make_transform_setup(session, sku="TRC-IDEM")
    await _receive_input(session, fx)

    await complete_task(
        session,
        task_id=fx["task"].id,
        good_quantity=Decimal("50"),
        defect_quantity=Decimal("0"),
        actor_id=fx["user"].id,
        idempotency_key="trc-idem:1",
    )
    await session.commit()

    replay = await complete_task(
        session,
        task_id=fx["task"].id,
        good_quantity=Decimal("50"),
        defect_quantity=Decimal("0"),
        actor_id=fx["user"].id,
        idempotency_key="trc-idem:1",
    )
    await session.commit()

    assert replay.get("idempotent_replay") is True
    assert await _tx_sum(session, fx["task"].id, Reason.TRANSFORM_CONSUME, DIMS_IN) == Decimal("50")
    assert await _tx_sum(session, fx["task"].id, Reason.COMPLETE, DIMS_OUT_A) == Decimal("50")
    await assert_no_stock_ledger_invariants_violations(session, context="transform-idem")


async def test_legacy_material_without_dimensions_consumed_from_null_group(
    session: AsyncSession,
) -> None:
    """Материал пришёл на пилу без габарита (до тикета #8 о сквозных
    перемещениях): вход списывается из legacy-группы, выходы — с габаритом."""
    fx = await _make_transform_setup(session, sku="TRC-LEG")
    await _receive_input(session, fx, dims=None)

    await complete_task(
        session,
        task_id=fx["task"].id,
        good_quantity=Decimal("100"),
        defect_quantity=Decimal("0"),
        actor_id=fx["user"].id,
    )
    await session.commit()

    product_id, saw_id = fx["product"].id, fx["saw"].id
    assert await _tx_sum(session, fx["task"].id, Reason.TRANSFORM_CONSUME, None) == Decimal("100")
    assert await _balance(session, product_id, saw_id, None) == Decimal("0")
    assert await _balance(session, product_id, saw_id, DIMS_OUT_A) == Decimal("100")
    assert await _balance(session, product_id, saw_id, DIMS_OUT_B) == Decimal("100")
    await assert_no_stock_ledger_invariants_violations(session, context="transform-legacy")
