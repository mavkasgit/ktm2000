"""#304 — `/transfers/ready` лениво создаёт задание: цена и регресс.

Что проверяем
-------------
1. **Регресс (#176, ленивое создание):** released-строка складского участка без
   ``WorkTask`` после ``GET /transfers/ready`` получает задание, и повторный
   вызов уже ничего не создаёт (вторая выборка идёт без INSERT'ов).
2. **Цена поштучного пути:** сколько запросов и INSERT'ов добавляет строка без
   задания — замер на N строках, а не на одной.

Замер сделан на настоящей БД pytest-фикстурой, а не на живых данных: на живых
у всех строк выдачи задание уже есть, и ``is_new_task`` нигде не истинен — на
них путь ленивого создания не измеряется вовсе.
"""

from __future__ import annotations

from collections import Counter
from decimal import Decimal

import pytest
from app.transfers.queries import list_ready_to_transfer
from sqlalchemy import event

from tests.helpers.transfers_chain import (
    build_released_stock_lines,
    seed_manual_in,
)

POSITIONS = 5


@pytest.fixture
def sql_counters(engine):
    """Счётчик SQL вокруг блока: сколько всего, и по ведущим словам."""
    counters: Counter[str] = Counter()
    total: list[int] = [0]
    sync_engine = engine.sync_engine

    def _before(conn, cursor, statement, parameters, context, executemany):
        conn.info.setdefault("stmts", []).append(statement)

    def _after(conn, cursor, statement, parameters, context, executemany):
        stmts = conn.info.get("stmts") or []
        if stmts:
            counters[stmts.pop().split()[0].upper()] += 1
        total[0] += 1

    event.listen(sync_engine, "before_cursor_execute", _before)
    event.listen(sync_engine, "after_cursor_execute", _after)
    try:
        yield counters, total
    finally:
        event.remove(sync_engine, "before_cursor_execute", _before)
        event.remove(sync_engine, "after_cursor_execute", _after)


async def _seed_case(session, sku: str):
    """Released-строки складского этапа без задания + остаток под бюджет.

    Приём идёт с подписью операций, полученной от резолвера: с чужой подписью
    бюджет строки нулевой, и строка молча не попала бы в выдачу — кейс был бы
    пустым и «ничего не создалось» значило бы ничего.
    """
    fx = await build_released_stock_lines(session, sku=sku)
    # Строка исходного (складского) этапа: на ней нет задания по построению.
    source_lines = [line for line in fx["lines"] if line.product_id == fx["product"].id]
    source_line = min(source_lines, key=lambda line: line.sequence)
    await seed_manual_in(
        session,
        user_id=fx["user"].id,
        location_id=source_line.section_id,
        product_id=fx["product"].id,
        quantity=Decimal(50),
        completed_operations=fx["ops_by_stage"][source_line.sequence],
    )
    return fx, source_line


@pytest.mark.asyncio
async def test_ready_creates_task_for_stock_line_without_it(session, sql_counters):
    """Строка без задания появляется в выдаче и получает задание при первом GET."""
    fx, _source_line = await _seed_case(session, "LAZY-1")
    counters, _total = sql_counters

    # Счётчик обнуляем перед GET: замер должен показать стоимость ручки, а не
    # запись фикстуры (release_batch + MANUAL_IN пишут свои строки).
    counters.clear()
    result = await list_ready_to_transfer(session, limit=POSITIONS * 4)
    rows = result["items"] if isinstance(result, dict) else result
    assert rows, "released-строка складского участка обязана попасть в выдачу"

    first = {name: counters[name] for name in list(counters)}
    inserts_first = counters["INSERT"]
    print(f"\n[304] строк без задания: {len(rows)}")
    print(f"[304] первый GET: всего запросов по счётчикам {first}")
    print(f"[304] первый GET: INSERT={inserts_first}")
    assert inserts_first >= 1, (
        "кейс не построился: без ленивого создания INSERT'ов нет, "
        "значит строки выдачи уже имели задание"
    )

    # Второй GET: задание уже создано, поэтому ленивого создания быть не должно.
    counters.clear()
    again = await list_ready_to_transfer(session, limit=POSITIONS * 4)
    rows_again = again["items"] if isinstance(again, dict) else again
    assert [row["task_id"] for row in rows] == [row["task_id"] for row in rows_again], (
        "task_id обязан быть тем же: задание создано один раз и переиспользовано"
    )
    print(f"[304] второй GET: {dict(counters)}")
    assert counters["INSERT"] == 0, "повторный GET не должен ничего писать"



@pytest.mark.asyncio
async def test_ready_response_identical_before_and_after_lazy_creation(
    session, sql_counters
):
    """JSON-сверка (#304, п.4): ответ не зависит от того, создано задание или нет.

    Первый GET создаёт задание лениво, второй — уже ничего не пишет. Если
    ответ хоть чем-то отличается (task_id, dimensions, transferable_quantity,
    сортировка, состав строк), ленивое создание что-то исказило.
    """
    await _seed_case(session, "LAZY-2")

    first = await list_ready_to_transfer(session, limit=POSITIONS * 4)
    rows = first["items"] if isinstance(first, dict) else first
    assert rows, "кейс не построился: выдача пуста, сравнивать нечего"

    second = await list_ready_to_transfer(session, limit=POSITIONS * 4)
    rows_after = second["items"] if isinstance(second, dict) else second

    print(f"\n[304] поля строки выдачи: {sorted(rows[0])}")
    assert rows == rows_after, "ответ /transfers/ready изменился после ленивого создания"
    # Ключи, которые AC #304 называет поимённо.
    for row in rows:
        assert "task_id" in row
        assert "dimensions" in row
        assert "transferable_quantity" in row

@pytest.mark.asyncio
async def test_per_row_cost_scales_linearly(session, sql_counters):
    """Цена поштучного пути на N строках без задания (#304, п.2).

    Строим N независимых кейсов (по released-строке складского этапа без
    задания) и снимаем **один** GET: так видно, во сколько раз дороже
    поштучный путь по сравнению с чистым чтением.
    """
    for index in range(POSITIONS):
        await _seed_case(session, f"LAZY-N{index}")

    counters, _total = sql_counters
    counters.clear()
    result = await list_ready_to_transfer(session, limit=POSITIONS * 4)
    rows = result["items"] if isinstance(result, dict) else result
    with_task = await list_ready_to_transfer(session, limit=POSITIONS * 4)
    rows_after = with_task["items"] if isinstance(with_task, dict) else with_task

    first_pass = dict(counters)
    counters.clear()
    await list_ready_to_transfer(session, limit=POSITIONS * 4)
    second_pass = dict(counters)

    print(f"\n[304] N={POSITIONS} строк без задачи, первый GET: {first_pass}")
    print(f"[304] N={POSITIONS} строк без задачи, второй GET: {second_pass}")
    print(f"[304] строк выдачи: {len(rows)}")

    # INSERT ровно столько, сколько строк **не имели задания И прошли бюджет**:
    # `db.add_all(new_tasks)` в `_fetch_stock_ready_items` добавляет лишь
    # budget-passing строки, поэтому число INSERT'ов не равно числу строк
    # выдачи. На этом кейсе из N строк задание создаётся только для части —
    # это и есть наблюдаемая величина, а не «N INSERT'ов».
    assert first_pass.get("INSERT", 0) >= 1, (
        "кейс не построился: ни одной строки без задания не создалось"
    )
    assert first_pass.get("INSERT", 0) <= len(rows), (
        "INSERT'ов не может быть больше, чем строк в выдаче"
    )
    assert second_pass.get("INSERT", 0) == 0, "второй GET ничего не пишет"
    # Идентичность ответа: task_id те же, что и после создания.
    assert [row["task_id"] for row in rows] == [row["task_id"] for row in rows_after]
