"""Тесты тикета #89: передача несёт dimensions из плана (WorkTask.dimensions).

Швы (TD, согласовано):
1. service ``transfer_send`` — match по длине нужной строки остатка, wrong length →
   «Insufficient stock», fallback на ``from_task.dimensions`` при пустом payload.
2. ``GET /api/transfers/ready`` — складской ``transferable`` ограничен группой
   размерности задания; готовые строки (stock и production) несут
   ``dimensions`` + ``dimensions_label``.
3. Создание ``WorkTask`` на 5 сайтах заполняет ``dimensions`` из плана.
"""
from __future__ import annotations

from datetime import date
from decimal import Decimal

import pytest
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.security import create_access_token
from app.models.internal_plan import SectionPlanLine
from app.models.product import Product, ProductType
from app.models.production_plan import (
    PlanPosition,
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
from app.models.work_task import WorkTask
from app.stock.models import QualityState, Reason, StockBalance
from app.stock.services import (
    StockCommand,
    StockCommandService,
    StockValidationError,
    dimensions_match_clause,
)
from app.transfers.services import transfer_send
from tests.test_integrity_invariants import assert_no_invariants_violations

pytestmark = pytest.mark.asyncio


# ─── helpers ──────────────────────────────────────────────────────────────


async def _make_user(session: AsyncSession, email: str = "dim@local") -> User:
    user = User(
        email=email,
        full_name="Dim Tester",
        role=UserRole.operator,
        is_active=True,
    )
    session.add(user)
    await session.flush()
    return user


def _auth_headers(user: User) -> dict[str, str]:
    token = create_access_token(subject=str(user.email))
    return {"Authorization": f"Bearer {token}"}


async def _make_dim_route_fixture(
    session: AsyncSession,
    *,
    sku: str,
    qty: Decimal,
    length_mm: float | None = None,
) -> dict:
    """raw_stock(SPG A) → prod1(SPG B) → prod2(SPG C, final).

    Все секции в разных ГХП: stock→prod1 и prod1→prod2 — кросс-ГХП передачи,
    обе видны в ready-списке. Позиция несёт ``input_dimensions`` (длину).
    """
    raw = Section(code=f"{sku}-RAW", name="RAW", type="raw_stock", is_active=True, sort_order=0)
    prod1 = Section(code=f"{sku}-P1", name="P1", type="production", is_active=True, sort_order=1)
    prod2 = Section(code=f"{sku}-P2", name="P2", type="production", is_active=True, sort_order=2)
    session.add_all([raw, prod1, prod2])
    await session.flush()

    spgs: list[StorageProductionGroup] = []
    for idx, (sec, code) in enumerate(
        [(raw, f"{sku}-A"), (prod1, f"{sku}-B"), (prod2, f"{sku}-C")]
    ):
        spg = StorageProductionGroup(code=code, name=code, is_active=True, sort_order=idx)
        session.add(spg)
        await session.flush()
        session.add(SpgSection(spg_id=spg.id, section_id=sec.id, sort_order=0))
        spgs.append(spg)

    product = Product(sku=sku, name=sku, type=ProductType.finished_good, unit="pcs", is_active=True)
    session.add(product)
    await session.flush()

    route = ProductionRoute(name=f"R-{sku}", is_active=True)
    session.add(route)
    await session.flush()
    for idx, (sec, code) in enumerate(
        [(raw, "ISSUE_RAW"), (prod1, "P1_OP"), (prod2, "P2_OP")], start=1
    ):
        st = RouteStage(route_id=route.id, sequence=idx, section_id=sec.id, is_final=(idx == 3))
        session.add(st)
        await session.flush()
        session.add(RouteOperation(route_stage_id=st.id, sequence=1, operation_code=code, operation_name=code))

    tech = Techcard(product_id=product.id, version="v1", is_active=True)
    session.add(tech)
    await session.flush()
    session.add(
        TechcardLine(techcard_id=tech.id, component_product_id=product.id, quantity=Decimal("1"), unit="pcs")
    )

    plan = ProductionPlan(
        plan_no=f"P-{sku}",
        name="p",
        status=ProductionPlanStatus.approved,
        period_start=date(2026, 5, 1),
        period_end=date(2026, 5, 31),
    )
    session.add(plan)
    await session.flush()

    pos = PlanPosition(
        production_plan_id=plan.id,
        product_id=product.id,
        source_type=PlanSourceType.manual,
        source_sku=product.sku,
        source_name=product.name,
        quantity=qty,
        input_dimensions={"length_mm": int(length_mm)} if length_mm is not None else None,
        source_payload={},
        status=PlanPositionStatus.approved,
        validation_status=PlanPositionValidationStatus.valid,
        validation_errors=[],
        period_start=plan.period_start,
        period_end=plan.period_end,
        has_pack_ops=False,
        route_id=route.id,
        route_assigned_at=None,
    )
    session.add(pos)
    await session.commit()
    return {
        "product": product,
        "plan": plan,
        "position": pos,
        "sections": [raw, prod1, prod2],
        "spgs": spgs,
    }


async def _release_via_take_to_work(client, position_id: int) -> None:
    resp = await client.post(
        "/api/production-planning/rows/take-to-work",
        json={"position_ids": [position_id]},
    )
    assert resp.status_code == 200, resp.text


async def _seed_balance(
    session: AsyncSession,
    *,
    user_id: int,
    location_id: int,
    product_id: int,
    qty: Decimal,
    dimensions: dict | None = None,
) -> None:
    svc = StockCommandService()
    await svc.record(
        session,
        StockCommand(
            product_id=product_id,
            to_location_id=location_id,
            quantity=qty,
            reason=Reason.MANUAL_IN,
            dimensions=dimensions,
            created_by=user_id,
        ),
    )
    await session.commit()


async def _balance_qty(
    session: AsyncSession,
    *,
    location_id: int,
    product_id: int,
    dimensions: dict | None,
) -> Decimal:
    bal = await session.scalar(
        select(StockBalance.balance_qty).where(
            StockBalance.location_id == location_id,
            StockBalance.product_id == product_id,
            StockBalance.quality_state == QualityState.GOOD,
            dimensions_match_clause(StockBalance.dimensions, dimensions),
        )
    )
    return bal or Decimal("0")


async def _stock_ready_task(client, user: User, section_id: int) -> int:
    resp = await client.get(f"/api/transfers/ready?section_id={section_id}", headers=_auth_headers(user))
    assert resp.status_code == 200, resp.text
    items = resp.json()["items"]
    assert len(items) == 1
    return items[0]["task_id"]


async def _complete_prod1_task(session: AsyncSession, *, sku: str, task: WorkTask, user: User) -> None:
    """Выдать материал на prod1 и завершить его (как _complete_source_tasks)."""
    stock = Section(code=f"{sku}-STK", name="Stock", type="raw_stock", is_active=True, sort_order=0)
    session.add(stock)
    await session.flush()
    svc = StockCommandService()
    await svc.record(
        session,
        StockCommand(
            product_id=task.product_id,
            from_location_id=None,
            to_location_id=stock.id,
            quantity=task.planned_quantity,
            reason=Reason.MANUAL_IN,
            created_by=user.id,
        ),
    )
    await svc.record(
        session,
        StockCommand(
            product_id=task.product_id,
            from_location_id=stock.id,
            to_location_id=task.section_id,
            quantity=task.planned_quantity,
            reason=Reason.TRANSFER_RECEIVE,
            task_id=task.id,
            created_by=user.id,
        ),
    )
    await svc.record(
        session,
        StockCommand(
            product_id=task.product_id,
            from_location_id=task.section_id,
            to_location_id=task.section_id,
            quantity=task.planned_quantity,
            reason=Reason.COMPLETE,
            task_id=task.id,
            source_ref="test_seed",
            created_by=user.id,
        ),
    )
    await session.commit()
    await assert_no_invariants_violations(session, context="complete-prod1")


# ─── Seam 1: transfer_send (match / wrong length / fallback) ───────────────


async def test_transfer_send_matches_dimension_balance_row(client, session) -> None:
    """transfer_send с длиной списывает только нужную группу остатка."""
    user = await _make_user(session, "dim-match@test.local")
    fx = await _make_dim_route_fixture(session, sku="DIMMAT", qty=Decimal("50"), length_mm=2000)
    raw_sec = fx["sections"][0]
    await _seed_balance(session, user_id=user.id, location_id=raw_sec.id,
                        product_id=fx["product"].id, qty=Decimal("100"), dimensions={"length_mm": 2000})
    await _seed_balance(session, user_id=user.id, location_id=raw_sec.id,
                        product_id=fx["product"].id, qty=Decimal("50"), dimensions={"length_mm": 3000})
    await _release_via_take_to_work(client, fx["position"].id)

    fake_task_id = await _stock_ready_task(client, user, raw_sec.id)

    await transfer_send(
        session,
        from_task_id=fake_task_id,
        to_task_id=None,
        quantity=Decimal("10"),
        actor_id=user.id,
        dimensions={"length_mm": 2000},
        allow_over_plan=True,
    )
    await session.commit()
    await assert_no_invariants_violations(session, context="match-dimension-transfer")

    assert await _balance_qty(session, location_id=raw_sec.id, product_id=fx["product"].id,
                              dimensions={"length_mm": 2000}) == Decimal("90")
    assert await _balance_qty(session, location_id=raw_sec.id, product_id=fx["product"].id,
                              dimensions={"length_mm": 3000}) == Decimal("50")


async def test_transfer_send_wrong_dimension_raises_insufficient_stock(client, session) -> None:
    """Другая длина, которой нет на складе → «Insufficient stock»."""
    user = await _make_user(session, "dim-wrong@test.local")
    fx = await _make_dim_route_fixture(session, sku="DIMWR", qty=Decimal("50"), length_mm=2000)
    raw_sec = fx["sections"][0]
    await _seed_balance(session, user_id=user.id, location_id=raw_sec.id,
                        product_id=fx["product"].id, qty=Decimal("100"), dimensions={"length_mm": 2000})
    await _release_via_take_to_work(client, fx["position"].id)

    fake_task_id = await _stock_ready_task(client, user, raw_sec.id)

    with pytest.raises(StockValidationError, match="Insufficient stock"):
        await transfer_send(
            session,
            from_task_id=fake_task_id,
            to_task_id=None,
            quantity=Decimal("10"),
            actor_id=user.id,
            dimensions={"length_mm": 3000},
            allow_over_plan=True,
        )


async def test_transfer_send_falls_back_to_from_task_dimensions(client, session) -> None:
    """Payload без dimensions → берём from_task.dimensions (регрессия тикета)."""
    user = await _make_user(session, "dim-fallback@test.local")
    fx = await _make_dim_route_fixture(session, sku="DIMFB", qty=Decimal("50"), length_mm=2000)
    raw_sec = fx["sections"][0]
    await _seed_balance(session, user_id=user.id, location_id=raw_sec.id,
                        product_id=fx["product"].id, qty=Decimal("100"), dimensions={"length_mm": 2000})
    await _release_via_take_to_work(client, fx["position"].id)

    fake_task_id = await _stock_ready_task(client, user, raw_sec.id)

    await transfer_send(
        session,
        from_task_id=fake_task_id,
        to_task_id=None,
        quantity=Decimal("10"),
        actor_id=user.id,
    )
    await session.commit()
    await assert_no_invariants_violations(session, context="fallback-transfer")

    assert await _balance_qty(session, location_id=raw_sec.id, product_id=fx["product"].id,
                              dimensions={"length_mm": 2000}) == Decimal("90")


# ─── Seam 2: ready list (stock transferable + dimensions/dimensions_label) ──


async def test_stock_transferable_limited_to_task_dimension_group(client, session) -> None:
    """Складской ready: transferable ограничен группой длины задания, не всем складом."""
    user = await _make_user(session, "dim-limit@test.local")
    fx = await _make_dim_route_fixture(session, sku="DIMLIM", qty=Decimal("200"), length_mm=2000)
    raw_sec = fx["sections"][0]
    await _seed_balance(session, user_id=user.id, location_id=raw_sec.id,
                        product_id=fx["product"].id, qty=Decimal("100"), dimensions={"length_mm": 2000})
    await _seed_balance(session, user_id=user.id, location_id=raw_sec.id,
                        product_id=fx["product"].id, qty=Decimal("1000"), dimensions={"length_mm": 3000})
    await _release_via_take_to_work(client, fx["position"].id)

    resp = await client.get(f"/api/transfers/ready?section_id={raw_sec.id}", headers=_auth_headers(user))
    assert resp.status_code == 200, resp.text
    items = resp.json()["items"]
    assert len(items) == 1
    assert items[0]["dimensions"] == {"length_mm": 2000}
    assert items[0]["dimensions_label"] == "2 м"
    # min(план 200, остаток 2000-группы 100) = 100, а не 1100 суммарно.
    assert items[0]["transferable_quantity"] == "100"
    # Сайт queries.py:741 — складской fake_task несёт габарит из плана.
    fake_task = await session.get(WorkTask, items[0]["task_id"])
    assert fake_task is not None and fake_task.dimensions == {"length_mm": 2000}


async def test_production_ready_row_carries_dimensions(client, session) -> None:
    """Production ready-строка несёт dimensions и dimensions_label из задания."""
    user = await _make_user(session, "dim-prodready@test.local")
    fx = await _make_dim_route_fixture(session, sku="DIMPRD", qty=Decimal("50"), length_mm=2000)
    await _release_via_take_to_work(client, fx["position"].id)

    tasks = (await session.execute(select(WorkTask).order_by(WorkTask.id))).scalars().all()
    assert len(tasks) == 2
    prod1_task = tasks[0]
    await _complete_prod1_task(session, sku="DIMPRD", task=prod1_task, user=user)

    prod1_sec = fx["sections"][1]
    resp = await client.get(f"/api/transfers/ready?section_id={prod1_sec.id}", headers=_auth_headers(user))
    assert resp.status_code == 200, resp.text
    items = resp.json()["items"]
    assert len(items) == 1
    assert items[0]["dimensions"] == {"length_mm": 2000}
    assert items[0]["dimensions_label"] == "2 м"


# ─── Seam 3: WorkTask.dimensions заполняется из плана (5 сайтов) ───────────


async def test_release_creates_tasks_with_dimensions_from_plan(client, session) -> None:
    """plan_generation: задания на production-секциях несут длину из плана."""
    fx = await _make_dim_route_fixture(session, sku="DIMREL", qty=Decimal("50"), length_mm=2000)
    await _release_via_take_to_work(client, fx["position"].id)

    tasks = (await session.execute(select(WorkTask).order_by(WorkTask.id))).scalars().all()
    assert len(tasks) == 2
    for task in tasks:
        assert task.dimensions == {"length_mm": 2000}


async def test_prepare_section_task_fills_dimensions(client, session) -> None:
    """operations_tasks.prepare_section_task: новое задание несёт длину из плана."""
    from app.services.shopfloor.operations_tasks import prepare_section_task

    user = await _make_user(session, "dim-prepare@test.local")
    fx = await _make_dim_route_fixture(session, sku="DIMPREP", qty=Decimal("50"), length_mm=2000)
    await _release_via_take_to_work(client, fx["position"].id)
    await session.execute(delete(WorkTask))
    await session.flush()

    prod1_sec = fx["sections"][1]
    result = await prepare_section_task(
        session,
        plan_position_id=fx["position"].id,
        section_id=prod1_sec.id,
        quantity=Decimal("50"),
        actor_id=user.id,
    )
    task = await session.get(WorkTask, result["task_id"])
    assert task is not None
    assert task.dimensions == {"length_mm": 2000}


async def test_auto_created_to_task_and_stock_fake_task_get_dimensions(client, session) -> None:
    """transfer_send auto-create + _get_or_create_stock_fake_task несут длину из плана."""
    from app.api.routes.production_planning import _get_or_create_stock_fake_task

    user = await _make_user(session, "dim-auto@test.local")
    fx = await _make_dim_route_fixture(session, sku="DIMAUTO", qty=Decimal("50"), length_mm=2000)
    raw_sec = fx["sections"][0]
    await _release_via_take_to_work(client, fx["position"].id)
    await session.execute(delete(WorkTask))
    await session.flush()
    await _seed_balance(session, user_id=user.id, location_id=raw_sec.id,
                        product_id=fx["product"].id, qty=Decimal("100"), dimensions={"length_mm": 2000})

    raw_line = (await session.execute(
        select(SectionPlanLine).where(SectionPlanLine.section_id == raw_sec.id)
    )).scalar_one()
    fake_task = await _get_or_create_stock_fake_task(
        session,
        stock_line=raw_line,
        stock_section=raw_sec,
        product_id=fx["product"].id,
    )
    assert fake_task.dimensions == {"length_mm": 2000}

    result = await transfer_send(
        session,
        from_task_id=fake_task.id,
        to_task_id=None,
        quantity=Decimal("10"),
        actor_id=user.id,
        allow_over_plan=True,
    )
    await session.commit()
    await assert_no_invariants_violations(session, context="auto-create-transfer")

    to_task = await session.get(WorkTask, result["to_task_id"])
    assert to_task is not None
    assert to_task.dimensions == {"length_mm": 2000}


async def test_auto_created_to_task_carries_sent_dimensions(client, session) -> None:
    """Auto-create: to_task несёт фактически переданный габарит (не план), ledger согласован."""
    from app.api.routes.production_planning import _get_or_create_stock_fake_task

    user = await _make_user(session, "dim-sent@test.local")
    # План длины 2000, но оператор передаёт 3000 (другая строка остатка).
    fx = await _make_dim_route_fixture(session, sku="DIMSENT", qty=Decimal("50"), length_mm=2000)
    raw_sec = fx["sections"][0]
    await _release_via_take_to_work(client, fx["position"].id)
    await session.execute(delete(WorkTask))
    await session.flush()
    await _seed_balance(session, user_id=user.id, location_id=raw_sec.id,
                        product_id=fx["product"].id, qty=Decimal("100"), dimensions={"length_mm": 3000})

    raw_line = (await session.execute(
        select(SectionPlanLine).where(SectionPlanLine.section_id == raw_sec.id)
    )).scalar_one()
    fake_task = await _get_or_create_stock_fake_task(
        session,
        stock_line=raw_line,
        stock_section=raw_sec,
        product_id=fx["product"].id,
    )
    assert fake_task.dimensions == {"length_mm": 2000}

    result = await transfer_send(
        session,
        from_task_id=fake_task.id,
        to_task_id=None,
        quantity=Decimal("10"),
        actor_id=user.id,
        dimensions={"length_mm": 3000},
        allow_over_plan=True,
    )
    await session.commit()
    await assert_no_invariants_violations(session, context="sent-dims-transfer")

    # to_task и проводки несут один и тот же габарит (3000), не план (2000).
    to_task = await session.get(WorkTask, result["to_task_id"])
    assert to_task is not None
    assert to_task.dimensions == {"length_mm": 3000}
    assert await _balance_qty(session, location_id=raw_sec.id, product_id=fx["product"].id,
                              dimensions={"length_mm": 3000}) == Decimal("90")
    assert await _balance_qty(session, location_id=raw_sec.id, product_id=fx["product"].id,
                              dimensions={"length_mm": 2000}) == Decimal("0")
