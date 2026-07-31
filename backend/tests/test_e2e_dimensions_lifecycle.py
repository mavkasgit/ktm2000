"""Сквозной E2E: длина от импорта остатков до пилы (тикет #9).

Полный производственный цикл с габаритами:
  импорт остатков 100 × 2,7 м → выпуск позиции → перемещения между секциями
  проносят габарит → пила режет 2,7 на 0,9 + 1,8 → баланс по длинам сходится.

Acceptance criteria:
- Интеграционный pytest: 100 × 2,7 м → 100 × 0,9 м + 100 × 1,8 м.
- assert_no_invariants_violations на КАЖДОМ шаге.
- Безразмерные продукты (null) проходят тот же маршрут без регрессий.
"""
from __future__ import annotations

from datetime import UTC, date, datetime
from decimal import Decimal
from io import BytesIO

import pytest
from openpyxl import Workbook
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.security import create_access_token
from app.models.dimension import DimensionType, ProductDimension
from app.models.internal_plan import SectionPlanLine
from app.models.product import Product, ProductType
from app.models.production_plan import (
    PlanPosition,
    PlanPositionRouteOrigin,
    PlanPositionStatus,
    PlanPositionValidationStatus,
    PlanSourceType,
    ProductionPlan,
    ProductionPlanStatus,
)
from app.models.route import ProductionRoute, RouteOperation, RouteStage
from app.models.section import Section
from app.models.spg import SpgSection, StorageProductionGroup
from app.models.techcard import Techcard, TechcardLine
from app.models.user import User, UserRole
from app.models.work_task import WorkTask, WorkTaskStatus
from app.stock import QualityState, Reason, StockCommand, StockCommandService
from app.stock.models import StockBalance, StockTransaction
from app.stock.services import dimensions_match_clause
from app.transfers.services import transfer_send

from tests.test_integrity_invariants import assert_no_invariants_violations

pytestmark = pytest.mark.asyncio

XLSX_MIME = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"


# ─── Helpers ────────────────────────────────────────────────────────────────────


async def _make_user(session: AsyncSession, email: str = "dim-e2e@local") -> User:
    user = User(
        email=email,
        password_hash="x",
        full_name="Dim E2E",
        role=UserRole.operator,
        is_active=True,
    )
    session.add(user)
    await session.flush()
    return user


def _auth_headers(user: User) -> dict[str, str]:
    return {"Authorization": f"Bearer {create_access_token(subject=user.email)}"}


async def _link_length_dimension(
    session: AsyncSession,
    product: Product,
    *,
    is_required: bool = True,
    default_value: float | None = None,
) -> None:
    dim_type = (
        await session.scalars(select(DimensionType).where(DimensionType.code == "length_mm"))
    ).first()
    if dim_type is None:
        dim_type = DimensionType(code="length_mm", name="Длина", unit="мм")
        session.add(dim_type)
        await session.flush()
    session.add(
        ProductDimension(
            product_id=product.id,
            dimension_type_id=dim_type.id,
            is_required=is_required,
            default_value=default_value,
        )
    )
    await session.flush()


def _make_remainders_excel(rows: list[tuple]) -> BytesIO:
    """Create .xlsx with headers (SKU, Количество, Длина, Комментарий)."""
    wb = Workbook()
    ws = wb.active
    ws.title = "Остатки"
    ws.append(["SKU", "Количество", "Длина", "Комментарий"])
    for row in rows:
        ws.append(list(row))
    buf = BytesIO()
    wb.save(buf)
    buf.seek(0)
    return buf


async def _make_dimensions_route(
    session: AsyncSession,
    sku: str,
    *,
    transform_stage_sequence: int = 4,
) -> tuple[Product, list[Section], ProductionRoute, list[RouteStage]]:
    """Маршрут: RAW_STOCK → DRILL → ANOD → SAWING(transform) → PACK → FG_STOCK.

    Секции 1 и 6 — склады (raw_stock / finished_stock), остальные — production.
    Этап ``transform_stage_sequence`` помечен transforms_dimensions=True.
    """
    product = Product(sku=sku, name=f"Profile {sku}", type=ProductType.finished_good, unit="pcs", is_active=True)
    session.add(product)
    await session.flush()

    sec_defs = [
        (f"{sku}-RAW", "Склад сырья", "raw_stock"),
        (f"{sku}-DRILL", "Сверловка", "production"),
        (f"{sku}-ANOD", "Анодирование", "production"),
        (f"{sku}-SAW", "Пила", "production"),
        (f"{sku}-PACK", "Упаковка", "production"),
        (f"{sku}-FG", "Склад ГП", "finished_stock"),
    ]
    sections = [Section(code=code, name=name, type=stype, is_active=True, sort_order=i) for i, (code, name, stype) in enumerate(sec_defs)]
    session.add_all(sections)
    await session.flush()

    # SPG: все секции в одной группе (упрощает перемещения).
    spg = StorageProductionGroup(code=f"{sku}-SPG", name="GHP", is_active=True, sort_order=0)
    session.add(spg)
    await session.flush()
    for i, sec in enumerate(sections):
        session.add(SpgSection(spg_id=spg.id, section_id=sec.id, sort_order=i))
    await session.flush()

    techcard = Techcard(product_id=product.id, version="v1", is_active=True)
    session.add(techcard)
    await session.flush()
    session.add(TechcardLine(techcard_id=techcard.id, component_product_id=product.id, quantity=Decimal("1"), unit="pcs"))

    route = ProductionRoute(name=f"Route {sku}", is_active=True)
    session.add(route)
    await session.flush()

    op_codes = ["ISSUE_RAW", "DRILL", "ANOD", "SAW", "PACK", "ACCEPT_FINISHED"]
    stages: list[RouteStage] = []
    for idx, (sec, op_code) in enumerate(zip(sections, op_codes, strict=True), start=1):
        stage = RouteStage(
            route_id=route.id,
            sequence=idx,
            section_id=sec.id,
            is_final=(idx == len(sections)),
            transforms_dimensions=(idx == transform_stage_sequence),
        )
        session.add(stage)
        await session.flush()
        session.add(RouteOperation(route_stage_id=stage.id, sequence=1, operation_code=op_code, operation_name=op_code))
        stages.append(stage)
    await session.flush()
    return product, sections, route, stages


async def _make_position_with_outputs(
    session: AsyncSession,
    product: Product,
    route: ProductionRoute,
    *,
    quantity: Decimal,
    input_quantity: Decimal | None = None,
    input_dimensions: dict | None = None,
    outputs: list[dict] | None = None,
) -> tuple[ProductionPlan, PlanPosition]:
    plan = ProductionPlan(
        plan_no=f"PLAN-DIM-{product.sku}",
        name="Dim E2E Plan",
        status=ProductionPlanStatus.approved,
        period_start=date(2026, 7, 1),
        period_end=date(2026, 7, 31),
    )
    session.add(plan)
    await session.flush()
    position = PlanPosition(
        production_plan_id=plan.id,
        product_id=product.id,
        source_type=PlanSourceType.manual,
        source_sku=product.sku,
        source_name=product.name,
        quantity=quantity,
        input_quantity=input_quantity,
        input_dimensions=input_dimensions,
        outputs=outputs or [],
        source_payload={},
        period_start=plan.period_start,
        period_end=plan.period_end,
        status=PlanPositionStatus.approved,
        validation_status=PlanPositionValidationStatus.valid,
        validation_errors=[],
        route_id=route.id,
        route_origin=PlanPositionRouteOrigin.manual_confirmed,
        route_assigned_at=datetime.now(UTC),
        route_manual_confirmed_at=datetime.now(UTC),
    )
    session.add(position)
    await session.flush()
    return plan, position


async def _release(client, plan: ProductionPlan, position: PlanPosition, quantity: str) -> None:
    create_resp = await client.post(
        f"/api/production-plans/{plan.id}/release-batches",
        json={"positions": [{"plan_position_id": position.id, "release_quantity": quantity}]},
    )
    assert create_resp.status_code == 201, create_resp.text
    release_resp = await client.post(f"/api/release-batches/{create_resp.json()['id']}/release")
    assert release_resp.status_code == 200, release_resp.text


async def _tasks_by_sequence(session: AsyncSession, position: PlanPosition) -> list[WorkTask]:
    return (
        await session.execute(
            select(WorkTask)
            .join(SectionPlanLine, WorkTask.section_plan_line_id == SectionPlanLine.id)
            .where(SectionPlanLine.plan_position_id == position.id)
            .order_by(SectionPlanLine.sequence)
        )
    ).scalars().all()


async def _get_balance(
    session: AsyncSession,
    product_id: int,
    location_id: int,
    dims: dict | None,
) -> Decimal:
    """Годный остаток габаритной группы на локации."""
    bal = await session.scalar(
        select(StockBalance.balance_qty).where(
            StockBalance.product_id == product_id,
            StockBalance.location_id == location_id,
            StockBalance.quality_state == QualityState.GOOD,
            dimensions_match_clause(StockBalance.dimensions, dims),
        )
    )
    return bal or Decimal("0")


async def _do_transfer(
    session: AsyncSession,
    from_task_id: int,
    to_task_id: int | None,
    quantity: Decimal,
    actor_id: int,
    dimensions: dict | None = None,
) -> dict:
    """Вызвать transfer_send напрямую (сервисный слой)."""
    return await transfer_send(
        session,
        from_task_id=from_task_id,
        to_task_id=to_task_id,
        quantity=quantity,
        actor_id=actor_id,
        dimensions=dimensions,
        allow_over_plan=True,
    )


async def _complete_task(
    client,
    task_id: int,
    good_quantity: str,
    defect_quantity: str = "0",
) -> dict:
    resp = await client.post(
        f"/api/shopfloor/tasks/{task_id}/complete",
        json={"good_quantity": good_quantity, "defect_quantity": defect_quantity},
    )
    assert resp.status_code == 200, resp.text
    return resp.json()


# ─── Main scenario: 100 × 2,7 м → 100 × 0,9 м + 100 × 1,8 м ──────────────────


async def test_dimensions_lifecycle_import_to_saw(client, session: AsyncSession) -> None:
    """Сквозной сценарий: остаток 100×2,7 м проходит маршрут и превращается
    в 100×0,9 м + 100×1,8 м на пиле. assert_no_invariants_violations на каждом шаге.
    """
    user = await _make_user(session)
    headers = _auth_headers(user)

    # ── Шаг 1: Создать продукт с привязкой длины и маршрут ──────────────────
    product, sections, route, stages = await _make_dimensions_route(
        session, "DIM-E2E", transform_stage_sequence=4
    )
    await _link_length_dimension(session, product, is_required=True, default_value=2700)
    await session.commit()

    raw_sec = sections[0]   # raw_stock
    drill_sec = sections[1]
    anod_sec = sections[2]
    saw_sec = sections[3]   # transforms_dimensions
    pack_sec = sections[4]
    fg_sec = sections[5]    # finished_stock

    await assert_no_invariants_violations(session, context="after-setup")

    # ── Шаг 2: Импорт остатков 100 × 2,7 м на склад сырья ──────────────────
    excel_buf = _make_remainders_excel([("DIM-E2E", 100, "2,7", None)])
    resp = await client.post(
        "/api/stock/import/remainders",
        files={"file": ("remainders.xlsx", excel_buf, XLSX_MIME)},
        data={
            "location_id": str(raw_sec.id),
            "quality_state": "good",
            "sheet_index": "0",
        },
        headers=headers,
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["success"] is True
    assert body["imported_count"] == 1

    # Баланс: 100 × 2700мм на складе сырья
    bal_raw = await _get_balance(session, product.id, raw_sec.id, {"length_mm": 2700})
    assert bal_raw == Decimal("100")
    await assert_no_invariants_violations(session, context="after-import-remainders")

    # ── Шаг 3: Создать позицию плана с outputs и выпустить ──────────────────
    outputs = [
        {"row_number": 1, "quantity": "100", "dimensions": {"length_mm": 900}},
        {"row_number": 2, "quantity": "100", "dimensions": {"length_mm": 1800}},
    ]
    plan, position = await _make_position_with_outputs(
        session,
        product,
        route,
        quantity=Decimal("200"),
        input_quantity=Decimal("100"),
        input_dimensions={"length_mm": 2700},
        outputs=outputs,
    )
    await session.commit()

    await _release(client, plan, position, "200")

    tasks = await _tasks_by_sequence(session, position)
    # Маршрут: RAW_STOCK (склад, нет WorkTask) → DRILL → ANOD → SAW → PACK → FG (склад, нет WorkTask)
    # Задания создаются только на production-секциях.
    assert len(tasks) == 4, f"Expected 4 tasks (production sections), got {len(tasks)}"

    # Задание пилы несёт спецификацию трансформации
    saw_task = tasks[2]  # SAW — 3-й production этап
    assert saw_task.input_quantity == Decimal("100")
    assert saw_task.input_dimensions == {"length_mm": 2700}
    assert len(saw_task.outputs) == 2
    await assert_no_invariants_violations(session, context="after-release")

    # ── Шаг 4: Перемещение со склада сырья на сверловку ─────────────────────
    drill_task = tasks[0]
    # Для первого production-этапа нужно передать материал со склада.
    # Начислим материал на участок через StockCommand (имитация выдачи со склада).
    svc = StockCommandService()
    await svc.record(session, StockCommand(
        product_id=product.id,
        from_location_id=raw_sec.id,
        to_location_id=drill_sec.id,
        quantity=Decimal("100"),
        reason=Reason.TRANSFER_SEND,
        dimensions={"length_mm": 2700},
        quality_state=QualityState.GOOD,
        task_id=drill_task.id,
        created_by=user.id,
        comment="Выдача сырья на сверловку",
    ))
    await svc.record(session, StockCommand(
        product_id=product.id,
        from_location_id=None,
        to_location_id=None,
        quantity=Decimal("100"),
        reason=Reason.TRANSFER_RECEIVE,
        dimensions={"length_mm": 2700},
        quality_state=QualityState.GOOD,
        task_id=drill_task.id,
        created_by=user.id,
        comment="Приём на сверловку",
    ))

    # Баланс: 100 × 2700мм переместилось на сверловку
    bal_drill = await _get_balance(session, product.id, drill_sec.id, {"length_mm": 2700})
    assert bal_drill == Decimal("100")
    bal_raw_after = await _get_balance(session, product.id, raw_sec.id, {"length_mm": 2700})
    assert bal_raw_after == Decimal("0")
    await assert_no_invariants_violations(session, context="after-transfer-to-drill")

    # ── Шаг 5: Завершить сверловку (100 шт) ─────────────────────────────────
    await _complete_task(client, drill_task.id, "100")
    await assert_no_invariants_violations(session, context="after-complete-drill")

    # ── Шаг 6: Перемещение на анодирование ──────────────────────────────────
    anod_task = tasks[1]
    await _do_transfer(
        session,
        from_task_id=drill_task.id,
        to_task_id=anod_task.id,
        quantity=Decimal("100"),
        actor_id=user.id,
        dimensions={"length_mm": 2700},
    )

    # Баланс: 100 × 2700мм на анодировании
    bal_anod = await _get_balance(session, product.id, anod_sec.id, {"length_mm": 2700})
    assert bal_anod == Decimal("100")
    await assert_no_invariants_violations(session, context="after-transfer-to-anod")

    # ── Шаг 7: Завершить анодирование (100 шт) ──────────────────────────────
    await _complete_task(client, anod_task.id, "100")
    await assert_no_invariants_violations(session, context="after-complete-anod")

    # ── Шаг 8: Перемещение на пилу ──────────────────────────────────────────
    await _do_transfer(
        session,
        from_task_id=anod_task.id,
        to_task_id=saw_task.id,
        quantity=Decimal("100"),
        actor_id=user.id,
        dimensions={"length_mm": 2700},
    )

    bal_saw = await _get_balance(session, product.id, saw_sec.id, {"length_mm": 2700})
    assert bal_saw == Decimal("100")
    await assert_no_invariants_violations(session, context="after-transfer-to-saw")

    # ── Шаг 9: Завершить пилу (трансформация 100 × 2,7 → 100 × 0,9 + 100 × 1,8) ──
    await _complete_task(client, saw_task.id, "100")

    # Баланс на пиле: 2700мм = 0 (списан), 900мм = 100, 1800мм = 100
    bal_saw_2700 = await _get_balance(session, product.id, saw_sec.id, {"length_mm": 2700})
    bal_saw_900 = await _get_balance(session, product.id, saw_sec.id, {"length_mm": 900})
    bal_saw_1800 = await _get_balance(session, product.id, saw_sec.id, {"length_mm": 1800})
    assert bal_saw_2700 == Decimal("0"), f"Expected 0, got {bal_saw_2700}"
    assert bal_saw_900 == Decimal("100"), f"Expected 100, got {bal_saw_900}"
    assert bal_saw_1800 == Decimal("100"), f"Expected 100, got {bal_saw_1800}"
    await assert_no_invariants_violations(session, context="after-saw-transform")

    # ── Шаг 10: Перемещение на упаковку (несёт 0,9 + 1,8) ──────────────────
    pack_task = tasks[3]
    # Передаём оба габарита через StockCommand (transfer_send ограничивает
    # одну активную передачу на задание; для мульти-габарита используем ledger).
    svc2 = StockCommandService()
    for dims_out in [{"length_mm": 900}, {"length_mm": 1800}]:
        await svc2.record(session, StockCommand(
            product_id=product.id,
            from_location_id=saw_sec.id,
            to_location_id=pack_sec.id,
            quantity=Decimal("100"),
            reason=Reason.TRANSFER_SEND,
            dimensions=dims_out,
            quality_state=QualityState.GOOD,
            task_id=saw_task.id,
            created_by=user.id,
            comment=f"Передача на упаковку {dims_out}",
        ))
        await svc2.record(session, StockCommand(
            product_id=product.id,
            from_location_id=None,
            to_location_id=None,
            quantity=Decimal("100"),
            reason=Reason.TRANSFER_RECEIVE,
            dimensions=dims_out,
            quality_state=QualityState.GOOD,
            task_id=pack_task.id,
            created_by=user.id,
            comment=f"Приём на упаковку {dims_out}",
        ))

    bal_pack_900 = await _get_balance(session, product.id, pack_sec.id, {"length_mm": 900})
    bal_pack_1800 = await _get_balance(session, product.id, pack_sec.id, {"length_mm": 1800})
    assert bal_pack_900 == Decimal("100")
    assert bal_pack_1800 == Decimal("100")
    await assert_no_invariants_violations(session, context="after-transfer-to-pack")


# ─── Dimensionless (null) scenario: same route, no regressions ─────────────────


async def test_dimensionless_lifecycle_no_regressions(client, session: AsyncSession) -> None:
    """Безразмерный продукт (dimensions=null) проходит тот же маршрут без регрессий."""
    user = await _make_user(session, email="dimless@local")
    headers = _auth_headers(user)

    # Маршрут без трансформации (transform_stage_sequence=None → ни один этап не трансформирует)
    product, sections, route, stages = await _make_dimensions_route(
        session, "NODIM-E2E", transform_stage_sequence=99  # нет этапа с маркером
    )
    # Не привязываем length dimension — продукт безразмерный
    await session.commit()

    raw_sec = sections[0]
    drill_sec = sections[1]
    anod_sec = sections[2]
    saw_sec = sections[3]

    await assert_no_invariants_violations(session, context="nodim-setup")

    # ── Импорт остатков без длины ───────────────────────────────────────────
    svc = StockCommandService()
    await svc.record(session, StockCommand(
        product_id=product.id,
        quantity=Decimal("100"),
        reason=Reason.MANUAL_IN,
        to_location_id=raw_sec.id,
        quality_state=QualityState.GOOD,
        created_by=user.id,
        comment="Безразмерный остаток",
    ))
    bal_raw = await _get_balance(session, product.id, raw_sec.id, None)
    assert bal_raw == Decimal("100")
    await assert_no_invariants_violations(session, context="nodim-after-import")

    # ── Позиция плана без dimensions ────────────────────────────────────────
    plan, position = await _make_position_with_outputs(
        session,
        product,
        route,
        quantity=Decimal("100"),
        input_quantity=None,
        input_dimensions=None,
        outputs=[],
    )
    await session.commit()

    await _release(client, plan, position, "100")

    tasks = await _tasks_by_sequence(session, position)
    assert len(tasks) == 4

    # Все задания без трансформации
    for task in tasks:
        assert task.input_quantity is None
        assert task.input_dimensions is None
        assert task.outputs == []
    await assert_no_invariants_violations(session, context="nodim-after-release")

    # ── Выдача на сверловку ─────────────────────────────────────────────────
    drill_task = tasks[0]
    await svc.record(session, StockCommand(
        product_id=product.id,
        from_location_id=raw_sec.id,
        to_location_id=drill_sec.id,
        quantity=Decimal("100"),
        reason=Reason.TRANSFER_SEND,
        dimensions=None,
        quality_state=QualityState.GOOD,
        task_id=drill_task.id,
        created_by=user.id,
    ))
    await svc.record(session, StockCommand(
        product_id=product.id,
        from_location_id=None,
        to_location_id=None,
        quantity=Decimal("100"),
        reason=Reason.TRANSFER_RECEIVE,
        dimensions=None,
        quality_state=QualityState.GOOD,
        task_id=drill_task.id,
        created_by=user.id,
    ))
    bal_drill = await _get_balance(session, product.id, drill_sec.id, None)
    assert bal_drill == Decimal("100")
    await assert_no_invariants_violations(session, context="nodim-after-transfer-drill")

    # ── Завершить сверловку ─────────────────────────────────────────────────
    await _complete_task(client, drill_task.id, "100")
    await assert_no_invariants_violations(session, context="nodim-after-complete-drill")

    # ── Перемещение на анодирование ─────────────────────────────────────────
    anod_task = tasks[1]
    await _do_transfer(
        session,
        from_task_id=drill_task.id,
        to_task_id=anod_task.id,
        quantity=Decimal("100"),
        actor_id=user.id,
        dimensions=None,
    )

    bal_anod = await _get_balance(session, product.id, anod_sec.id, None)
    assert bal_anod == Decimal("100")
    await assert_no_invariants_violations(session, context="nodim-after-transfer-anod")

    # ── Завершить анодирование ──────────────────────────────────────────────
    await _complete_task(client, anod_task.id, "100")
    await assert_no_invariants_violations(session, context="nodim-after-complete-anod")

    # ── Перемещение на пилу (обычный этап, без трансформации) ───────────────
    saw_task = tasks[2]
    await _do_transfer(
        session,
        from_task_id=anod_task.id,
        to_task_id=saw_task.id,
        quantity=Decimal("100"),
        actor_id=user.id,
        dimensions=None,
    )

    bal_saw = await _get_balance(session, product.id, saw_sec.id, None)
    assert bal_saw == Decimal("100")
    await assert_no_invariants_violations(session, context="nodim-after-transfer-saw")

    # ── Завершить пилу (обычное завершение, без трансформации) ──────────────
    await _complete_task(client, saw_task.id, "100")

    # Баланс на пиле остаётся 100 (net-zero COMPLETE: from=section, to=section)
    bal_saw_after = await _get_balance(session, product.id, saw_sec.id, None)
    assert bal_saw_after == Decimal("100")
    await assert_no_invariants_violations(session, context="nodim-after-complete-saw")
