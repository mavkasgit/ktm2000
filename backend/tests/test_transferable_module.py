"""Шов глубокого модуля ``app.transfers.transferable`` (тикет #131).

Проверяем публичный интерфейс напрямую (не через готовую страницу):
- :func:`task_transferable_lines` — read-эквивалент гидраторов ready-page;
- :func:`task_transferable` — write-guard ``transfer_send``/``correct_transfer``;
- dispatch по трём веткам (plain / transform / stock) и выбор формулы по
  финальности участка живут внутри модуля и согласованы по построению.

Интеграционные сценарии (three-way сверка с ready-SQL) — в
``test_transfer_budget_consistency.py``; здесь — контракт самого шва.
"""
from __future__ import annotations

from decimal import Decimal

import pytest
from sqlalchemy import select

from app.models.work_task import WorkTask
from app.transfers.transferable import (
    BudgetKind,
    task_transferable,
    task_transferable_lines,
)

from tests.stock.test_transfer_stage2 import _make_two_ghp_setup
from tests.test_integrity_invariants import (
    _make_user,
    _release_via_take_to_work,
    assert_no_invariants_violations,
)
from tests.test_transfer_dimensions import (
    _complete_saw,
    _make_dim_route_fixture,
    _make_transform_route_fixture,
    _seed_balance,
    _tasks_for_position,
)
from tests.test_transfer_budget_consistency import _ready_row

pytestmark = pytest.mark.asyncio


# ─── 1. plain: одна строка, received не участвует ────────────────────────────


async def test_plain_line_and_write_guard_share_sources(client, session) -> None:
    """plain: completed=5, received=10, transferred=2 → строка и guard = 3.

    ``received`` не входит в бюджет ни в одной из веток шва — бывший T6 теперь
    свойство общей реализации, а не договорённости.
    """
    setup = await _make_two_ghp_setup(session, sku="TBSEAM", qty=Decimal("10"))
    user = setup["user"]
    sec1 = setup["sections"][0]
    sec2 = setup["sections"][1]
    await _release_via_take_to_work(client, setup["position"].id)

    from_task = (
        await session.execute(select(WorkTask).where(WorkTask.section_id == sec1.id))
    ).scalar_one()
    to_task = (
        await session.execute(select(WorkTask).where(WorkTask.section_id == sec2.id))
    ).scalar_one()

    from app.stock import Reason, StockCommand, StockCommandService

    stock_sec = await _seed_manual_in_stock(session)
    svc = StockCommandService()
    await svc.record(
        session,
        StockCommand(
            product_id=from_task.product_id,
            from_location_id=None,
            to_location_id=stock_sec.id,
            quantity=Decimal("10"),
            reason=Reason.MANUAL_IN,
            created_by=user.id,
        ),
    )
    await svc.record(
        session,
        StockCommand(
            product_id=from_task.product_id,
            from_location_id=stock_sec.id,
            to_location_id=from_task.section_id,
            quantity=Decimal("10"),
            reason=Reason.TRANSFER_RECEIVE,
            task_id=from_task.id,
            created_by=user.id,
        ),
    )
    await svc.record(
        session,
        StockCommand(
            product_id=from_task.product_id,
            from_location_id=from_task.section_id,
            to_location_id=from_task.section_id,
            quantity=Decimal("5"),
            reason=Reason.COMPLETE,
            task_id=from_task.id,
            source_ref="test_seed",
            created_by=user.id,
        ),
    )
    await session.commit()

    result = await _transfer_via_module(
        session, from_task_id=from_task.id, to_task_id=to_task.id, quantity=Decimal("2"),
        actor_id=user.id,
    )
    assert result["status"] == "accepted"
    await session.commit()
    await assert_no_invariants_violations(session, context="seam-plain")

    lines = await task_transferable_lines(session, from_task)
    assert len(lines) == 1
    line = lines[0]
    assert line.kind is BudgetKind.PLAIN
    assert line.is_final is False
    assert line.dims == from_task.dimensions
    assert line.planned == Decimal("10")
    assert line.produced == Decimal("5")
    # «Использовано» — net переданное (2), а не полученное (10).
    assert line.used == Decimal("2")
    assert line.budget == Decimal("3")

    assert await task_transferable(session, from_task) == Decimal("3")


# ─── 2. transform: строки по выходам + точечный lookup ──────────────────────


async def test_transform_lines_and_point_lookup_agree(client, session) -> None:
    """transform: строки выхода 900/1800; точечный лимит сходится со строками."""
    user = await _make_user(session, "tbseam-saw@local")
    fx = await _make_transform_route_fixture(
        session,
        sku="TBSEAMSAW",
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

    result = await _transfer_via_module(
        session, from_task_id=saw_task.id, quantity=Decimal("40"),
        actor_id=user.id, dimensions={"length_mm": 900},
    )
    assert result["status"] == "accepted"
    await session.commit()
    await assert_no_invariants_violations(session, context="seam-transform")

    lines = await task_transferable_lines(session, saw_task)
    assert [line.dims for line in lines] == [
        {"length_mm": 900}, {"length_mm": 1800},
    ]
    by_dims = {
        tuple(sorted((line.dims or {}).items())): line for line in lines
    }
    line_900 = by_dims[(("length_mm", 900),)]
    line_1800 = by_dims[(("length_mm", 1800),)]

    for line in (line_900, line_1800):
        assert line.kind is BudgetKind.TRANSFORM
        assert line.is_final is False
        assert line.produced == Decimal("100")
    assert line_900.used == Decimal("40")
    assert line_900.budget == Decimal("60")
    assert line_1800.used == Decimal("0")
    assert line_1800.budget == Decimal("100")

    # Точечный write-guard по тем же строкам produced.
    assert await task_transferable(
        session, saw_task, dimensions={"length_mm": 900}
    ) == Decimal("60")
    assert await task_transferable(
        session, saw_task, dimensions={"length_mm": 1800}
    ) == Decimal("100")
    # Размер вне спецификации передавать нельзя (инвариант D2).
    assert await task_transferable(
        session, saw_task, dimensions={"length_mm": 500}
    ) == Decimal("0")


# ─── 3. финальный участок: смысл бюджета — отправка ─────────────────────────


async def test_final_stage_lines_use_send_semantics(client, session) -> None:
    """Финальный этап: used = FINAL_RELEASE, формула remaining_send.

    Строки шва и отдельный владелец чтения отправки (#128) возвращают одно
    число — расхождение семантик невозможно по построению.
    """
    from app.services.shopfloor import send_budget
    from app.services.shopfloor.operations_tasks import final_release

    user = await _make_user(session, "tbseam-final@local")
    fx = await _make_transform_route_fixture(
        session,
        sku="TBSEAMFIN",
        qty=Decimal("100"),
        input_quantity=Decimal("100"),
        input_dimensions={"length_mm": 2700},
        outputs=[{"row_number": 1, "quantity": "100", "dimensions": {"length_mm": 900}}],
        final_transform=True,
    )
    await _release_via_take_to_work(client, fx["position"].id)
    saw_task = (await _tasks_for_position(session, fx["position"].id))[0]
    await _complete_saw(session, saw_task=saw_task, user=user)

    result = await final_release(
        session, task_id=saw_task.id, quantity=Decimal("40"), actor_id=user.id,
    )
    await session.commit()
    assert result["transaction_id"]

    lines = await task_transferable_lines(session, saw_task)
    assert len(lines) == 1
    line = lines[0]
    assert line.kind is BudgetKind.TRANSFORM
    assert line.is_final is True
    assert line.produced == Decimal("100")
    assert line.used == Decimal("40")  # выпущено, не передано
    assert line.budget == Decimal("60")

    assert await send_budget.remaining_send(
        session, task=saw_task, dims={"length_mm": 900}
    ) == Decimal("60")


# ─── 4. stock: строка складской задачи ──────────────────────────────────────


async def test_stock_line_tracks_plan_and_physical_stock(client, session) -> None:
    """stock: план 100, остаток 100 → строка 100; после отгрузки 40 → 60."""
    user = await _make_user(session, "tbseam-stock@local")
    fx = await _make_dim_route_fixture(session, sku="TBSEAMSTK", qty=Decimal("100"))
    raw_sec = fx["sections"][0]
    await _seed_balance(
        session,
        user_id=user.id,
        location_id=raw_sec.id,
        product_id=fx["product"].id,
        qty=Decimal("100"),
        dimensions=None,
    )
    await _release_via_take_to_work(client, fx["position"].id)

    row_before = await _ready_row(client, user, raw_sec.id)
    assert row_before["transferable_quantity"] == "100"
    fake_task = await session.get(WorkTask, row_before["task_id"])
    assert fake_task is not None

    result = await _transfer_via_module(
        session, from_task_id=fake_task.id, quantity=Decimal("40"), actor_id=user.id,
    )
    assert result["status"] == "accepted"
    await session.commit()
    await assert_no_invariants_violations(session, context="seam-stock")

    lines = await task_transferable_lines(session, fake_task)
    assert len(lines) == 1
    line = lines[0]
    assert line.kind is BudgetKind.STOCK
    assert line.is_final is False
    assert line.planned == Decimal("100")
    assert line.produced == Decimal("60")  # физический остаток после отгрузки
    assert line.used == Decimal("40")      # уже передано
    assert line.budget == Decimal("60")    # min(план-остаток, физ. остаток)

    assert await task_transferable(session, fake_task) == Decimal("60")


# ─── helpers ────────────────────────────────────────────────────────────────


async def _seed_manual_in_stock(session):
    """Складская секция для ручного прихода (аналог сценария оракула #107)."""
    from app.models.section import Section

    stock_sec = Section(
        code="TBSEAM-STK", name="Stock", type="raw_stock", is_active=True, sort_order=0
    )
    session.add(stock_sec)
    await session.flush()
    return stock_sec


async def _transfer_via_module(session, *, from_task_id, actor_id, quantity,
                               to_task_id=None, dimensions=None) -> dict:
    """Передача через доменную запись (write-path, как в проде)."""
    from app.transfers.services import transfer_send

    return await transfer_send(
        session,
        from_task_id=from_task_id,
        to_task_id=to_task_id,
        quantity=quantity,
        actor_id=actor_id,
        dimensions=dimensions,
    )
