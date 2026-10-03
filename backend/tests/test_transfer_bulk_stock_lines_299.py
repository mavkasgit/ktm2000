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
    """Счётчик SQL на время блока с ``try/finally`` — по образцу тестов #290.

    ``sql`` — сами начала запросов: регресс ниже считает не «сколько всего»,
    а «сколько раз понадобился вот этот запрос», и общее число тут обманчиво
    (на N задач прибавляются ещё и чтения секций).
    """
    counter = {"n": 0, "sql": []}
    sync_engine = session.bind.sync_engine

    def _count(conn, cursor, statement, parameters, context, executemany):
        counter["n"] += 1
        counter["sql"].append(" ".join(statement.split()))

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
async def test_stock_branch_scales_sublinearly(client, session) -> None:
    """Складская ветка не растёт по числу задач: `stock_line_bulk` — один вызов.

    Регресс #299 (найдено на ревью среза R10): подсказка `lines` убрала
    повторные `db.get` строки плана, но сам bulk-ядро вызывался ПО ОДНОМУ
    разу на задачу, списком из одного элемента. Внутри ядра на каждый такой
    выходятся свои запросы — операции этапа, net TRANSFER_SEND и остатки, —
    поэтому «bulk»-ветка линейно росла вместе с числом складских строк
    (замер: 9 SQL на задачу, N=1/2/4 → 9/18/36).

    Проверка не по «всего SQL», а по тому, сколько раз понадобился КАЖДЫЙ из
    трёх запросов ядра: на старом коде их было бы по два на две задачи, здесь
    — по одному. Общее число запросов для такой проверки не годится: оно
    линейно растёт из-за чтений секций и это нормально.
    """
    from app.transfers.transferable import task_transferable_lines_bulk

    tasks: list[WorkTask] = []
    line_hints: dict[int, SectionPlanLine] = {}
    for i in range(2):
        task, _section = await _one_stock_task(client, session, sku=f"T299SCALE{i}")
        plan_line = (
            await session.execute(
                select(SectionPlanLine).where(
                    SectionPlanLine.id == task.section_plan_line_id
                )
            )
        ).scalar_one()
        tasks.append(task)
        line_hints[plan_line.id] = plan_line

    # Холодная карта сессии: иначе identity-map съел бы те самые чтения,
    # ради которых ветка и батчится, и замер вышел бы нулевым на обоих кодах.
    session.expunge_all()
    counter, remove = _count_sql(session)
    try:
        bulk = await task_transferable_lines_bulk(session, tasks, lines=line_hints)
    finally:
        remove()

    assert set(bulk) == {task.id for task in tasks}
    ops = [s for s in counter["sql"] if "route_operations" in s and "DISTINCT" in s]
    net = [s for s in counter["sql"] if "FROM stock_transactions" in s]
    balances = [s for s in counter["sql"] if "FROM stock_balances" in s]
    # Две строки плана — две пары (route_id, sequence), и операции этапа
    # читаются по одной на пару: это ожидаемо, ядро их кэширует на вызов.
    assert len(ops) == 2, f"операции этапов прочитаны {len(ops)} раз, ожидалось 2"
    # А вот эти два — на ВСЮ выборку: по запросу на задачу означало бы, что
    # ядро вызвалось поштучно.
    assert len(net) == 1, f"net TRANSFER_SEND прочитан {len(net)} раз, ожидался 1"
    assert len(balances) == 1, f"остатки прочитаны {len(balances)} раз, ожидался 1"


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
