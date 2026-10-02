"""Регресс N+1 складской ветки бюджета (#299, пункты 2–3).

`task_transferable_lines_bulk` раньше добирал строку плана дважды на задачу:
в `_stock_planned_qty` и снова внутри `stock_line_bulk`. Повторы гасил
identity-map, поэтому на готовой странице это было незаметно — но стоило
двух запросов на КАЖДУЮ НОВУЮ строку плана. Здесь подсказка `lines`
проверяется числом SQL: с ней и без неё разница ровно в этих запросах,
а ответ совпадает.
"""

from __future__ import annotations

from decimal import Decimal

import pytest
from app.models.internal_plan import SectionPlanLine
from app.models.work_task import WorkTask
from sqlalchemy import event, select

from tests.test_integrity_invariants import _make_user, _release_via_take_to_work
from tests.test_transfer_budget_consistency import _ready_row
from tests.test_transfer_dimensions import _make_dim_route_fixture, _seed_balance

pytestmark = pytest.mark.asyncio


def _count_sql(session):
    """Счётчик SQL на время блока с ``try/finally`` — по образцу тестов #290."""
    counter = {"n": 0}
    sync_engine = session.bind.sync_engine

    def _count(conn, cursor, statement, parameters, context, executemany):
        counter["n"] += 1

    event.listen(sync_engine, "before_cursor_execute", _count)
    return counter, lambda: event.remove(sync_engine, "before_cursor_execute", _count)


async def _one_stock_task(client, session, *, sku: str):
    """Складская задача на объёмном участке: остаток есть, бюджет считается."""
    user = await _make_user(session, f"{sku.lower()}@local")
    fx = await _make_dim_route_fixture(session, sku=sku, qty=Decimal(100))
    raw_sec = fx["sections"][0]
    await _seed_balance(
        session,
        user_id=user.id,
        location_id=raw_sec.id,
        product_id=fx["product"].id,
        qty=Decimal(100),
        dimensions=None,
    )
    await _release_via_take_to_work(client, fx["position"].id)
    row = await _ready_row(client, user, raw_sec.id)
    task = (
        await session.execute(select(WorkTask).where(WorkTask.id == row["task_id"]))
    ).scalar_one()
    return task, raw_sec


@pytest.mark.asyncio
async def test_lines_hint_removes_per_task_plan_line_reads(client, session) -> None:
    """С подсказкой `lines` складская ветка не читает строки плана поштучно.

    Проверка на одной и той же задаче: без подсказки ветка добирается до её
    строки плана сама (это и есть N+1 — два запроса на задачу на холодной
    карте), с подсказкой — не ходит. Ответ обязан совпасть.
    """
    from app.transfers.transferable import task_transferable_lines_bulk

    task, section = await _one_stock_task(client, session, sku="T299LINES")
    plan_line = (
        await session.execute(
            select(SectionPlanLine).where(
                SectionPlanLine.id == task.section_plan_line_id
            )
        )
    ).scalar_one()

    counter_cold, remove_cold = _count_sql(session)
    try:
        # Первая выборка в этом замере: карта сессии ещё холодная.
        session.expunge_all()
        cold = await task_transferable_lines_bulk(session, [task])
    finally:
        remove_cold()

    counter_hint, remove_hint = _count_sql(session)
    try:
        hinted = await task_transferable_lines_bulk(
            session,
            [task],
            sections={section.id: section},
            lines={plan_line.id: plan_line},
        )
    finally:
        remove_hint()

    assert counter_cold["n"] > counter_hint["n"], (
        f"без подсказки {counter_cold['n']} SQL, с подсказкой {counter_hint['n']} — "
        "подсказка не даёт эффекта"
    )
    assert hinted == cold


@pytest.mark.asyncio
async def test_bulk_and_single_stock_paths_agree(client, session) -> None:
    """Строки батча и одиночного пути совпадают по бюджету и плану."""
    from app.transfers.transferable import (
        task_transferable_lines,
        task_transferable_lines_bulk,
    )

    task, section = await _one_stock_task(client, session, sku="T299AGREE")

    bulk = await task_transferable_lines_bulk(session, [task], sections={section.id: section})
    single = await task_transferable_lines(session, task, section=section)

    assert len(bulk[task.id]) == len(single) == 1
    assert bulk[task.id][0].budget == single[0].budget
    assert bulk[task.id][0].planned == single[0].planned
