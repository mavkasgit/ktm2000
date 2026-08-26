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

from collections.abc import Sequence
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
from app.stock.models import QualityState, Reason, StockBalance, StockTransaction
from app.stock.services import (
    StockCommand,
    StockCommandService,
    StockValidationError,
    dimensions_match_clause,
)
from app.transfers.services import cancel_transfer, correct_transfer, transfer_send
from tests.test_integrity_invariants import assert_no_invariants_violations
# Канонические определения фабрик живут в tests/helpers/transfers.py
# (#131 follow-up); реэкспорт сохраняет старый путь импорта для потребителей.
from tests.helpers.transfers import (
    _complete_saw,
    _make_dim_route_fixture,
    _make_transform_route_fixture,
    _seed_balance,
    _tasks_for_position,
)

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


async def _release_via_take_to_work(client, position_id: int) -> None:
    resp = await client.post(
        "/api/production-planning/rows/take-to-work",
        json={"position_ids": [position_id]},
    )
    assert resp.status_code == 200, resp.text


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


# ─── Seam 4 (#90): Transfer.dimensions + guard по паре (задача, размер) ────


async def test_transfer_send_writes_transfer_dimensions(client, session) -> None:
    """transfer_send записывает Transfer.dimensions (канонический размер)."""
    from app.models.transfer import Transfer

    user = await _make_user(session, "dim-xferdims@test.local")
    fx = await _make_dim_route_fixture(session, sku="DIMDIMS", qty=Decimal("50"), length_mm=2000)
    raw_sec = fx["sections"][0]
    await _seed_balance(session, user_id=user.id, location_id=raw_sec.id,
                        product_id=fx["product"].id, qty=Decimal("100"), dimensions={"length_mm": 2000})
    await _release_via_take_to_work(client, fx["position"].id)

    fake_task_id = await _stock_ready_task(client, user, raw_sec.id)
    result = await transfer_send(
        session,
        from_task_id=fake_task_id,
        to_task_id=None,
        quantity=Decimal("10"),
        actor_id=user.id,
        allow_over_plan=True,
    )
    await session.commit()

    transfer = await session.get(Transfer, result["transfer_id"])
    assert transfer is not None
    assert transfer.dimensions == {"length_mm": 2000}
    await assert_no_invariants_violations(session, context="transfer-dimensions")


async def test_multiple_transfers_same_dimension_allowed_within_transferable(client, session) -> None:
    """Несколько передач одного размера разрешены; суммарно ≤ transferable."""
    user = await _make_user(session, "dim-multisend@test.local")
    fx = await _make_dim_route_fixture(session, sku="DIMMULTI", qty=Decimal("100"), length_mm=2000)
    raw_sec = fx["sections"][0]
    await _seed_balance(session, user_id=user.id, location_id=raw_sec.id,
                        product_id=fx["product"].id, qty=Decimal("100"), dimensions={"length_mm": 2000})
    await _release_via_take_to_work(client, fx["position"].id)

    fake_task_id = await _stock_ready_task(client, user, raw_sec.id)

    # Первая передача 40 — укладывается в план (100).
    r1 = await transfer_send(
        session,
        from_task_id=fake_task_id,
        to_task_id=None,
        quantity=Decimal("40"),
        actor_id=user.id,
    )
    await session.commit()
    assert r1["status"] == "accepted"

    # Вторая передача 30 того же размера — разрешена (сумма 70 ≤ 100).
    r2 = await transfer_send(
        session,
        from_task_id=fake_task_id,
        to_task_id=None,
        quantity=Decimal("30"),
        actor_id=user.id,
    )
    await session.commit()
    assert r2["status"] == "accepted"

    # Третья 31 → превышение (сумма была бы 101 > 100).
    with pytest.raises(ValueError, match="exceeds transferable"):
        await transfer_send(
            session,
            from_task_id=fake_task_id,
            to_task_id=None,
            quantity=Decimal("31"),
            actor_id=user.id,
        )

    await assert_no_invariants_violations(session, context="multi-send-dimension")


async def test_ready_transferable_decreases_by_dimension_sent(client, session) -> None:
    """ready: transferable по размеру уменьшается на уже переданное по нему."""
    user = await _make_user(session, "dim-transferable@test.local")
    fx = await _make_dim_route_fixture(session, sku="DIMTRF", qty=Decimal("100"), length_mm=2000)
    raw_sec = fx["sections"][0]
    await _seed_balance(session, user_id=user.id, location_id=raw_sec.id,
                        product_id=fx["product"].id, qty=Decimal("100"), dimensions={"length_mm": 2000})
    await _release_via_take_to_work(client, fx["position"].id)

    fake_task_id = await _stock_ready_task(client, user, raw_sec.id)
    await transfer_send(
        session,
        from_task_id=fake_task_id,
        to_task_id=None,
        quantity=Decimal("40"),
        actor_id=user.id,
    )
    await session.commit()

    resp = await client.get(f"/api/transfers/ready?section_id={raw_sec.id}", headers=_auth_headers(user))
    assert resp.status_code == 200, resp.text
    items = resp.json()["items"]
    assert len(items) == 1
    assert items[0]["dimensions"] == {"length_mm": 2000}
    # 100 план − 40 переданное = 60.
    assert items[0]["transferable_quantity"] == "60"


# ─── Seam 5 (#8/#89/#90): трансформирующий этап — инварианты D2/D3 ─────────


async def _task_transferable_by_dim(
    session: AsyncSession, task: WorkTask, dims: dict | None
) -> Decimal:
    from app.transfers.transferable import task_transferable

    return await task_transferable(session, task, dimensions=dims)


async def test_transforming_task_multi_transfer_within_output_quantity(client, session) -> None:
    """D2: с трансформирующего задания нельзя передать размера больше выхода;
    несколько передач одного размера разрешены в пределах transferable."""
    user = await _make_user(session, "dim-saw@test.local")
    fx = await _make_transform_route_fixture(
        session,
        sku="SAW1",
        qty=Decimal("100"),
        input_quantity=Decimal("100"),
        input_dimensions={"length_mm": 2700},
        outputs=[
            {"row_number": 1, "quantity": "100", "dimensions": {"length_mm": 900}},
            {"row_number": 2, "quantity": "100", "dimensions": {"length_mm": 1800}},
        ],
    )
    await _release_via_take_to_work(client, fx["position"].id)
    saw_task = (await _tasks_for_position(session, fx["position"].id))[0]
    assert saw_task.outputs, "saw task должен нести выходы"
    await _complete_saw(session, saw_task=saw_task, user=user)

    r1 = await transfer_send(
        session,
        from_task_id=saw_task.id,
        to_task_id=None,
        quantity=Decimal("40"),
        actor_id=user.id,
        dimensions={"length_mm": 900},
    )
    await session.commit()
    assert r1["status"] == "accepted"

    r2 = await transfer_send(
        session,
        from_task_id=saw_task.id,
        to_task_id=None,
        quantity=Decimal("30"),
        actor_id=user.id,
        dimensions={"length_mm": 900},
    )
    await session.commit()
    assert r2["status"] == "accepted"

    # Третья 31 → сумма 101 > выхода 100 → отказ (кап по outputs, D2).
    with pytest.raises(ValueError, match="exceeds transferable"):
        await transfer_send(
            session,
            from_task_id=saw_task.id,
            to_task_id=None,
            quantity=Decimal("31"),
            actor_id=user.id,
            dimensions={"length_mm": 900},
        )
    await session.commit()

    # Другой размер (1800) не затронут — передаём весь выход.
    r3 = await transfer_send(
        session,
        from_task_id=saw_task.id,
        to_task_id=None,
        quantity=Decimal("100"),
        actor_id=user.id,
        dimensions={"length_mm": 1800},
    )
    await session.commit()
    assert r3["status"] == "accepted"

    await assert_no_invariants_violations(session, context="saw-multi-transfer")


async def test_transforming_task_cancel_isolation_between_sizes(client, session) -> None:
    """Отмена передачи одного размера не трогает transferable другого (D1/D2)."""
    user = await _make_user(session, "dim-sawcancel@test.local")
    fx = await _make_transform_route_fixture(
        session,
        sku="SAWCL",
        qty=Decimal("100"),
        input_quantity=Decimal("100"),
        input_dimensions={"length_mm": 2700},
        outputs=[
            {"row_number": 1, "quantity": "100", "dimensions": {"length_mm": 900}},
            {"row_number": 2, "quantity": "100", "dimensions": {"length_mm": 1800}},
        ],
    )
    await _release_via_take_to_work(client, fx["position"].id)
    saw_task = (await _tasks_for_position(session, fx["position"].id))[0]
    await _complete_saw(session, saw_task=saw_task, user=user)

    t900 = await transfer_send(
        session,
        from_task_id=saw_task.id,
        to_task_id=None,
        quantity=Decimal("40"),
        actor_id=user.id,
        dimensions={"length_mm": 900},
    )
    await session.commit()
    t1800 = await transfer_send(
        session,
        from_task_id=saw_task.id,
        to_task_id=None,
        quantity=Decimal("60"),
        actor_id=user.id,
        dimensions={"length_mm": 1800},
    )
    await session.commit()

    await cancel_transfer(session, transfer_id=t900["transfer_id"], actor_id=user.id)
    await session.commit()

    # 900 — снова свободно; 1800 не затронут (60/100 передано).
    assert await _task_transferable_by_dim(session, saw_task, {"length_mm": 900}) == Decimal("100")
    assert await _task_transferable_by_dim(session, saw_task, {"length_mm": 1800}) == Decimal("40")

    r = await transfer_send(
        session,
        from_task_id=saw_task.id,
        to_task_id=None,
        quantity=Decimal("40"),
        actor_id=user.id,
        dimensions={"length_mm": 1800},
    )
    await session.commit()
    assert r["status"] == "accepted"
    r2 = await transfer_send(
        session,
        from_task_id=saw_task.id,
        to_task_id=None,
        quantity=Decimal("100"),
        actor_id=user.id,
        dimensions={"length_mm": 900},
    )
    await session.commit()
    assert r2["status"] == "accepted"
    with pytest.raises(ValueError, match="exceeds transferable"):
        await transfer_send(
            session,
            from_task_id=saw_task.id,
            to_task_id=None,
            quantity=Decimal("1"),
            actor_id=user.id,
            dimensions={"length_mm": 900},
        )
    await session.commit()

    await assert_no_invariants_violations(session, context="saw-cancel-isolation")


async def test_transforming_task_correct_isolation_between_sizes(client, session) -> None:
    """Коррекция количества одного размера не влияет на transferable другого."""
    user = await _make_user(session, "dim-sawcorrect@test.local")
    fx = await _make_transform_route_fixture(
        session,
        sku="SAWCR",
        qty=Decimal("100"),
        input_quantity=Decimal("100"),
        input_dimensions={"length_mm": 2700},
        outputs=[
            {"row_number": 1, "quantity": "100", "dimensions": {"length_mm": 900}},
            {"row_number": 2, "quantity": "100", "dimensions": {"length_mm": 1800}},
        ],
    )
    await _release_via_take_to_work(client, fx["position"].id)
    saw_task = (await _tasks_for_position(session, fx["position"].id))[0]
    await _complete_saw(session, saw_task=saw_task, user=user)

    t900 = await transfer_send(
        session,
        from_task_id=saw_task.id,
        to_task_id=None,
        quantity=Decimal("40"),
        actor_id=user.id,
        dimensions={"length_mm": 900},
    )
    await session.commit()

    await correct_transfer(
        session,
        transfer_id=t900["transfer_id"],
        new_quantity=Decimal("10"),
        actor_id=user.id,
    )
    await session.commit()

    # 900: 10/100 передано → transferable 90; 1800 не затронут (100).
    assert await _task_transferable_by_dim(session, saw_task, {"length_mm": 900}) == Decimal("90")
    assert await _task_transferable_by_dim(session, saw_task, {"length_mm": 1800}) == Decimal("100")

    r = await transfer_send(
        session,
        from_task_id=saw_task.id,
        to_task_id=None,
        quantity=Decimal("90"),
        actor_id=user.id,
        dimensions={"length_mm": 900},
    )
    await session.commit()
    assert r["status"] == "accepted"
    with pytest.raises(ValueError, match="exceeds transferable"):
        await transfer_send(
            session,
            from_task_id=saw_task.id,
            to_task_id=None,
            quantity=Decimal("1"),
            actor_id=user.id,
            dimensions={"length_mm": 900},
        )
    await session.commit()

    await assert_no_invariants_violations(session, context="saw-correct-isolation")


async def test_final_release_transforming_stage_carries_output_dimensions(client, session) -> None:
    """D3: FINAL_RELEASE на трансформирующем финальном этапе несёт выходной размер."""
    from app.services.shopfloor.operations_tasks import final_release

    user = await _make_user(session, "dim-final@test.local")
    fx = await _make_transform_route_fixture(
        session,
        sku="SAWFIN",
        qty=Decimal("100"),
        input_quantity=Decimal("100"),
        input_dimensions={"length_mm": 2700},
        outputs=[{"row_number": 1, "quantity": "100", "dimensions": {"length_mm": 900}}],
        final_transform=True,
    )
    await _release_via_take_to_work(client, fx["position"].id)
    saw_task = (await _tasks_for_position(session, fx["position"].id))[0]
    await _complete_saw(session, saw_task=saw_task, user=user)

    # Один выход — габарит выводится из спецификации автоматически.
    result = await final_release(
        session,
        task_id=saw_task.id,
        quantity=Decimal("100"),
        actor_id=user.id,
    )
    await session.commit()
    assert result["transaction_id"]

    tx = await session.scalar(
        select(StockTransaction).where(
            StockTransaction.task_id == saw_task.id,
            StockTransaction.reason == Reason.FINAL_RELEASE,
        )
    )
    assert tx is not None
    assert tx.dimensions == {"length_mm": 900}
    await assert_no_invariants_violations(session, context="final-release-dims")

    # Чужой размер → отказ (не выход спецификации).
    with pytest.raises(ValueError, match="must match one of the task outputs"):
        await final_release(
            session,
            task_id=saw_task.id,
            quantity=Decimal("1"),
            actor_id=user.id,
            dimensions={"length_mm": 1800},
        )


async def test_final_release_transforming_stage_multiple_outputs_require_dimensions(client, session) -> None:
    """D3: несколько выходов — финальный выпуск требует явный dimensions."""
    from app.services.shopfloor.operations_tasks import final_release

    user = await _make_user(session, "dim-finalmulti@test.local")
    fx = await _make_transform_route_fixture(
        session,
        sku="SAWFIN2",
        qty=Decimal("100"),
        input_quantity=Decimal("100"),
        input_dimensions={"length_mm": 2700},
        outputs=[
            {"row_number": 1, "quantity": "100", "dimensions": {"length_mm": 900}},
            {"row_number": 2, "quantity": "100", "dimensions": {"length_mm": 1800}},
        ],
        final_transform=True,
    )
    await _release_via_take_to_work(client, fx["position"].id)
    saw_task = (await _tasks_for_position(session, fx["position"].id))[0]
    await _complete_saw(session, saw_task=saw_task, user=user)

    with pytest.raises(ValueError, match="requires dimensions"):
        await final_release(
            session,
            task_id=saw_task.id,
            quantity=Decimal("50"),
            actor_id=user.id,
        )

    # Явный размер — выпуск проходит и несёт габарит.
    result = await final_release(
        session,
        task_id=saw_task.id,
        quantity=Decimal("50"),
        actor_id=user.id,
        dimensions={"length_mm": 900},
    )
    await session.commit()
    assert result["transaction_id"]

    tx = await session.scalar(
        select(StockTransaction).where(
            StockTransaction.task_id == saw_task.id,
            StockTransaction.reason == Reason.FINAL_RELEASE,
            dimensions_match_clause(StockTransaction.dimensions, {"length_mm": 900}),
        )
    )
    assert tx is not None
    assert tx.dimensions == {"length_mm": 900}
    await assert_no_invariants_violations(session, context="final-release-multi")


# ─── Seam 6 (#91): готово к передаче по (задача, размер) + авто-передача ────


def _ready_by_length(items: list[dict]) -> dict[int, dict]:
    """Ready-строки резки, сгруппированные по length_mm выхода."""
    result: dict[int, dict] = {}
    for item in items:
        dims = item.get("dimensions")
        length = dims.get("length_mm") if isinstance(dims, dict) else None
        if length is not None:
            result[int(length)] = item
    return result


async def test_ready_cutting_two_output_rows(client, session) -> None:
    """Тикет #91: ready-строки резки — по строке на каждый выход (задача, размер)."""
    user = await _make_user(session, "dim-sawready@test.local")
    fx = await _make_transform_route_fixture(
        session,
        sku="SAWRDY",
        qty=Decimal("100"),
        input_quantity=Decimal("100"),
        input_dimensions={"length_mm": 2700},
        outputs=[
            {"row_number": 1, "quantity": "100", "dimensions": {"length_mm": 900}},
            {"row_number": 2, "quantity": "100", "dimensions": {"length_mm": 1800}},
        ],
    )
    await _release_via_take_to_work(client, fx["position"].id)
    saw_task = (await _tasks_for_position(session, fx["position"].id))[0]
    await _complete_saw(session, saw_task=saw_task, user=user)

    saw_sec = fx["sections"][1]
    resp = await client.get(f"/api/transfers/ready?section_id={saw_sec.id}", headers=_auth_headers(user))
    assert resp.status_code == 200, resp.text
    items = resp.json()["items"]
    assert len(items) == 2
    by_len = _ready_by_length(items)
    assert set(by_len) == {900, 1800}
    assert by_len[900]["dimensions"] == {"length_mm": 900}
    assert by_len[900]["dimensions_label"] == "0,9 м"
    assert by_len[900]["planned_quantity"] == "100"
    assert by_len[900]["transferable_quantity"] == "100"
    assert by_len[1800]["dimensions"] == {"length_mm": 1800}
    assert by_len[1800]["transferable_quantity"] == "100"


async def test_ready_cutting_transferable_decreases_by_size(client, session) -> None:
    """Тикет #91: transferable строки выхода падает на уже переданное по размеру."""
    user = await _make_user(session, "dim-sawtrf@test.local")
    fx = await _make_transform_route_fixture(
        session,
        sku="SAWTRF",
        qty=Decimal("100"),
        input_quantity=Decimal("100"),
        input_dimensions={"length_mm": 2700},
        outputs=[
            {"row_number": 1, "quantity": "100", "dimensions": {"length_mm": 900}},
            {"row_number": 2, "quantity": "100", "dimensions": {"length_mm": 1800}},
        ],
    )
    await _release_via_take_to_work(client, fx["position"].id)
    saw_task = (await _tasks_for_position(session, fx["position"].id))[0]
    await _complete_saw(session, saw_task=saw_task, user=user)

    await transfer_send(
        session,
        from_task_id=saw_task.id,
        to_task_id=None,
        quantity=Decimal("40"),
        actor_id=user.id,
        dimensions={"length_mm": 900},
    )
    await session.commit()

    saw_sec = fx["sections"][1]
    resp = await client.get(f"/api/transfers/ready?section_id={saw_sec.id}", headers=_auth_headers(user))
    assert resp.status_code == 200, resp.text
    items = resp.json()["items"]
    assert len(items) == 2
    by_len = _ready_by_length(items)
    assert by_len[900]["transferable_quantity"] == "60"
    assert by_len[900]["already_transferred_quantity"] == "40"
    assert by_len[1800]["transferable_quantity"] == "100"


async def test_ready_cutting_transferable_capped_by_produced(client, session) -> None:
    """Тикет #91: частичная порция — transferable не больше фактически раскроенного."""
    from app.services.shopfloor.operations_tasks import complete_task

    user = await _make_user(session, "dim-sawpart@test.local")
    fx = await _make_transform_route_fixture(
        session,
        sku="SAWPART",
        qty=Decimal("100"),
        input_quantity=Decimal("100"),
        input_dimensions={"length_mm": 2700},
        outputs=[
            {"row_number": 1, "quantity": "100", "dimensions": {"length_mm": 900}},
            {"row_number": 2, "quantity": "100", "dimensions": {"length_mm": 1800}},
        ],
    )
    await _release_via_take_to_work(client, fx["position"].id)
    saw_task = (await _tasks_for_position(session, fx["position"].id))[0]

    svc = StockCommandService()
    await svc.record(
        session,
        StockCommand(
            product_id=saw_task.product_id,
            from_location_id=None,
            to_location_id=saw_task.section_id,
            quantity=Decimal("100"),
            reason=Reason.MANUAL_IN,
            dimensions={"length_mm": 2700},
            created_by=user.id,
        ),
    )
    await session.commit()
    await complete_task(
        session,
        task_id=saw_task.id,
        good_quantity=Decimal("50"),
        defect_quantity=Decimal("0"),
        actor_id=user.id,
    )
    await session.commit()

    saw_sec = fx["sections"][1]
    resp = await client.get(f"/api/transfers/ready?section_id={saw_sec.id}", headers=_auth_headers(user))
    assert resp.status_code == 200, resp.text
    items = resp.json()["items"]
    assert len(items) == 2
    by_len = _ready_by_length(items)
    assert by_len[900]["planned_quantity"] == "100"
    assert by_len[900]["completed_quantity"] == "50"
    assert by_len[900]["transferable_quantity"] == "50"
    assert by_len[1800]["transferable_quantity"] == "50"
    await assert_no_invariants_violations(session, context="ready-partial-cut")


async def test_auto_transfer_next_creates_per_output_transfers(client, session) -> None:
    """Тикет #91: авто-передача после завершения резки — по передаче на каждый выход."""
    from app.models.transfer import Transfer
    from app.services.shopfloor.operations_tasks import complete_task

    user = await _make_user(session, "dim-sawauto@test.local")
    fx = await _make_transform_route_fixture(
        session,
        sku="SAWAUTO",
        qty=Decimal("100"),
        input_quantity=Decimal("100"),
        input_dimensions={"length_mm": 2700},
        outputs=[
            {"row_number": 1, "quantity": "100", "dimensions": {"length_mm": 900}},
            {"row_number": 2, "quantity": "100", "dimensions": {"length_mm": 1800}},
        ],
        separate_ghps=True,
    )
    await _release_via_take_to_work(client, fx["position"].id)
    saw_task = (await _tasks_for_position(session, fx["position"].id))[0]

    svc = StockCommandService()
    await svc.record(
        session,
        StockCommand(
            product_id=saw_task.product_id,
            from_location_id=None,
            to_location_id=saw_task.section_id,
            quantity=Decimal("100"),
            reason=Reason.MANUAL_IN,
            dimensions={"length_mm": 2700},
            created_by=user.id,
        ),
    )
    await session.commit()
    await complete_task(
        session,
        task_id=saw_task.id,
        good_quantity=Decimal("100"),
        defect_quantity=Decimal("0"),
        actor_id=user.id,
        auto_transfer_next=True,
        idempotency_key="auto-saw-per-output",
    )
    await session.commit()
    await assert_no_invariants_violations(session, context="auto-per-output")

    transfers = (
        await session.execute(
            select(Transfer)
            .where(Transfer.from_task_id == saw_task.id)
            .order_by(Transfer.id)
        )
    ).scalars().all()
    assert len(transfers) == 2
    by_len: dict[int, Transfer] = {}
    for transfer in transfers:
        dims = transfer.dimensions or {}
        length = dims.get("length_mm")
        if length is not None:
            by_len[int(length)] = transfer
    assert set(by_len) == {900, 1800}
    assert by_len[900].sent_quantity == Decimal("100")
    assert by_len[1800].sent_quantity == Decimal("100")


async def test_auto_transfer_next_duplicate_output_size_does_not_overflow(client, session) -> None:
    """Тикет #91: дублирующиеся выходы одного размера не удваивают бюджет авто-передачи."""
    from app.models.transfer import Transfer
    from app.services.shopfloor.operations_tasks import complete_task

    user = await _make_user(session, "dim-sawdup@test.local")
    fx = await _make_transform_route_fixture(
        session,
        sku="SAWDUP",
        qty=Decimal("100"),
        input_quantity=Decimal("100"),
        input_dimensions={"length_mm": 2700},
        outputs=[
            {"row_number": 1, "quantity": "60", "dimensions": {"length_mm": 900}},
            {"row_number": 2, "quantity": "40", "dimensions": {"length_mm": 900}},
        ],
        separate_ghps=True,
    )
    await _release_via_take_to_work(client, fx["position"].id)
    saw_task = (await _tasks_for_position(session, fx["position"].id))[0]

    svc = StockCommandService()
    await svc.record(
        session,
        StockCommand(
            product_id=saw_task.product_id,
            from_location_id=None,
            to_location_id=saw_task.section_id,
            quantity=Decimal("100"),
            reason=Reason.MANUAL_IN,
            dimensions={"length_mm": 2700},
            created_by=user.id,
        ),
    )
    await session.commit()
    # Частичная порция: раскроено 50 заготовок → произведено 50 × 900.
    await complete_task(
        session,
        task_id=saw_task.id,
        good_quantity=Decimal("50"),
        defect_quantity=Decimal("0"),
        actor_id=user.id,
        auto_transfer_next=True,
        idempotency_key="auto-saw-dup",
    )
    await session.commit()
    await assert_no_invariants_violations(session, context="auto-dup-size")

    transfers = (
        await session.execute(
            select(Transfer)
            .where(Transfer.from_task_id == saw_task.id)
            .order_by(Transfer.id)
        )
    ).scalars().all()
    # Суммарно передано не больше фактически раскроенного размера (50).
    assert sum(t.sent_quantity for t in transfers) == Decimal("50")
    for transfer in transfers:
        assert (transfer.dimensions or {}).get("length_mm") == 900


# ─── Seam 7 (#95): доска несёт transferred_quantity по выходу; журнал/входящие — dimensions ─


async def _saw_board_task(client, user: User, saw_sec: Section, task_id: int) -> dict:
    resp = await client.get(
        f"/api/shopfloor/sections/{saw_sec.id}/board?limit=500",
        headers=_auth_headers(user),
    )
    assert resp.status_code == 200, resp.text
    tasks = resp.json()["tasks"]
    match = [t for t in tasks if t["id"] == task_id]
    assert len(match) == 1, f"задание {task_id} не найдено на доске пилы"
    return match[0]


async def test_board_outputs_progress_carries_transferred_by_output(client, session) -> None:
    """Тикет #95: outputs_progress доски несёт «Передано» по (задача, размер выхода)."""
    user = await _make_user(session, "dim-boardtf@test.local")
    fx = await _make_transform_route_fixture(
        session,
        sku="SAWBTF",
        qty=Decimal("100"),
        input_quantity=Decimal("100"),
        input_dimensions={"length_mm": 2700},
        outputs=[
            {"row_number": 1, "quantity": "100", "dimensions": {"length_mm": 900}},
            {"row_number": 2, "quantity": "100", "dimensions": {"length_mm": 1800}},
        ],
    )
    await _release_via_take_to_work(client, fx["position"].id)
    saw_task = (await _tasks_for_position(session, fx["position"].id))[0]
    await _complete_saw(session, saw_task=saw_task, user=user)

    # Передали часть одного выхода — «Передано» строки 900 = 40, 1800 = 0.
    await transfer_send(
        session,
        from_task_id=saw_task.id,
        to_task_id=None,
        quantity=Decimal("40"),
        actor_id=user.id,
        dimensions={"length_mm": 900},
    )
    await session.commit()

    saw_sec = fx["sections"][1]
    board_task = await _saw_board_task(client, user, saw_sec, saw_task.id)
    assert board_task["transforms_dimensions"] is True
    progress = board_task["outputs_progress"]
    assert progress is not None and len(progress) == 2
    by_len = {entry["dimensions"]["length_mm"]: entry for entry in progress}
    assert by_len[900]["quantity"] == "100"
    assert by_len[900]["produced_quantity"] == "100"
    assert by_len[900]["transferred_quantity"] == "40"
    assert by_len[1800]["quantity"] == "100"
    assert by_len[1800]["produced_quantity"] == "100"
    assert by_len[1800]["transferred_quantity"] == "0"
    await assert_no_invariants_violations(session, context="board-outputs-transferred")


async def test_transfer_history_carries_dimensions(client, session) -> None:
    """Тикет #95: журнал передач несёт dimensions (колонка «Размер»)."""
    from app.models.transfer import Transfer

    user = await _make_user(session, "dim-hxdim@test.local")
    fx = await _make_dim_route_fixture(session, sku="HXDIM", qty=Decimal("50"), length_mm=2000)
    raw_sec = fx["sections"][0]
    await _seed_balance(session, user_id=user.id, location_id=raw_sec.id,
                        product_id=fx["product"].id, qty=Decimal("100"), dimensions={"length_mm": 2000})
    await _release_via_take_to_work(client, fx["position"].id)

    fake_task_id = await _stock_ready_task(client, user, raw_sec.id)
    result = await transfer_send(
        session,
        from_task_id=fake_task_id,
        to_task_id=None,
        quantity=Decimal("10"),
        actor_id=user.id,
        dimensions={"length_mm": 2000},
        allow_over_plan=True,
    )
    await session.commit()
    transfer = await session.get(Transfer, result["transfer_id"])
    assert transfer is not None and transfer.dimensions == {"length_mm": 2000}

    resp = await client.get("/api/transfers/history", headers=_auth_headers(user))
    assert resp.status_code == 200, resp.text
    item = next(t for t in resp.json()["transfers"] if t["transfer_id"] == result["transfer_id"])
    assert item["dimensions"] == {"length_mm": 2000}


# ─── Seam 8 (#96): финальные строки в ready-list — is_final, releasable ─────


async def _complete_task_generic(session: AsyncSession, *, task: WorkTask, user: User) -> None:
    """Выдать материал на задачу и завершить её (как _complete_prod1_task)."""
    from app.models.work_task import WorkTaskStatus
    from app.stock.services import StockCommand, StockCommandService

    svc = StockCommandService()
    await svc.record(
        session,
        StockCommand(
            product_id=task.product_id,
            from_location_id=None,
            to_location_id=task.section_id,
            quantity=task.planned_quantity,
            reason=Reason.MANUAL_IN,
            created_by=user.id,
            # Габарит материала (ADR-0001): физический остаток по размеру.
            dimensions=task.dimensions,
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
            # Габарит задания (ADR-0001): releasable считается по (задача, размер).
            dimensions=task.dimensions,
        ),
    )
    # Снятие статуса ожидания: материал фактически выдан и завершён —
    # ready-список исключает только waiting_previous/cancelled.
    task.status = WorkTaskStatus.completed
    await session.commit()
    await assert_no_invariants_violations(session, context="complete-final-task")


async def test_ready_final_plain_row_is_final_with_releasable(client, session) -> None:
    """Тикет #96: финальный этап — ready-строка несёт is_final и releasable.

    prod2 — финальный production-этап; его задача попадает в ready-список
    без следующего шага: has_next_step=False, is_final=True, transferable =
    releasable (completed − already released).
    """
    user = await _make_user(session, "dim-finalready@test.local")
    fx = await _make_dim_route_fixture(session, sku="DIMFRD", qty=Decimal("50"), length_mm=2000)
    await _release_via_take_to_work(client, fx["position"].id)

    tasks = (await session.execute(select(WorkTask).order_by(WorkTask.id))).scalars().all()
    assert len(tasks) == 2
    prod1_task, prod2_task = tasks
    await _complete_task_generic(session, task=prod2_task, user=user)

    prod2_sec = fx["sections"][2]
    resp = await client.get(f"/api/transfers/ready?section_id={prod2_sec.id}", headers=_auth_headers(user))
    assert resp.status_code == 200, resp.text
    items = resp.json()["items"]
    assert len(items) == 1
    row = items[0]
    assert row["task_id"] == prod2_task.id
    assert row["is_final"] is True
    assert row["has_next_step"] is False
    assert row["next_section_id"] is None
    assert row["dimensions"] == {"length_mm": 2000}
    assert row["transferable_quantity"] == "50"

    # Частичный выпуск уменьшает releasable.
    from app.services.shopfloor.operations_tasks import final_release

    await final_release(
        session,
        task_id=prod2_task.id,
        quantity=Decimal("30"),
        actor_id=user.id,
        dimensions={"length_mm": 2000},
    )
    await session.commit()

    resp = await client.get(f"/api/transfers/ready?section_id={prod2_sec.id}", headers=_auth_headers(user))
    assert resp.status_code == 200, resp.text
    items = resp.json()["items"]
    assert len(items) == 1
    assert items[0]["transferable_quantity"] == "20"
    assert items[0]["already_transferred_quantity"] == "30"
    await assert_no_invariants_violations(session, context="final-plain-ready")


async def test_ready_final_transform_rows_are_final_with_releasable_per_size(client, session) -> None:
    """Тикет #96: финальный трансформирующий этап — по строке на размер.

    Резка (final_transform=True): две ready-строки (0,9 / 1,8), каждая
    is_final=True, has_next_step=False; transferable = releasable по размеру.
    После частичного выпуска одного размера падает только его строка.
    """
    from app.services.shopfloor.operations_tasks import final_release

    user = await _make_user(session, "dim-finaltrans@test.local")
    fx = await _make_transform_route_fixture(
        session,
        sku="SAWFINRD",
        qty=Decimal("100"),
        input_quantity=Decimal("100"),
        input_dimensions={"length_mm": 2700},
        outputs=[
            {"row_number": 1, "quantity": "100", "dimensions": {"length_mm": 900}},
            {"row_number": 2, "quantity": "100", "dimensions": {"length_mm": 1800}},
        ],
        final_transform=True,
    )
    await _release_via_take_to_work(client, fx["position"].id)
    saw_task = (await _tasks_for_position(session, fx["position"].id))[0]
    assert saw_task.outputs, "saw task должен нести выходы"
    await _complete_saw(session, saw_task=saw_task, user=user)

    saw_sec = fx["sections"][1]
    resp = await client.get(f"/api/transfers/ready?section_id={saw_sec.id}", headers=_auth_headers(user))
    assert resp.status_code == 200, resp.text
    items = resp.json()["items"]
    assert len(items) == 2
    by_len = _ready_by_length(items)
    assert set(by_len) == {900, 1800}
    for length in (900, 1800):
        assert by_len[length]["is_final"] is True
        assert by_len[length]["has_next_step"] is False
        assert by_len[length]["next_section_id"] is None
        assert by_len[length]["transferable_quantity"] == "100"

    # Частичный выпуск размера 900 — releasable падает только у него.
    await final_release(
        session,
        task_id=saw_task.id,
        quantity=Decimal("40"),
        actor_id=user.id,
        dimensions={"length_mm": 900},
    )
    await session.commit()

    resp = await client.get(f"/api/transfers/ready?section_id={saw_sec.id}", headers=_auth_headers(user))
    assert resp.status_code == 200, resp.text
    items = resp.json()["items"]
    assert len(items) == 2
    by_len = _ready_by_length(items)
    assert by_len[900]["transferable_quantity"] == "60"
    assert by_len[900]["already_transferred_quantity"] == "40"
    assert by_len[1800]["transferable_quantity"] == "100"
    await assert_no_invariants_violations(session, context="final-transform-ready")
    await assert_no_invariants_violations(session, context="history-dimensions")
