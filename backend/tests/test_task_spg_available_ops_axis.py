"""Ось «пройденные операции» в «доступно заданию» со склада (ADR-0055, #236).

`GET /api/shopfloor/tasks/{task_id}/spg-available` суммировал `balance_qty` по
`(артикул, питающий склад, GOOD)` — без пятой оси ключа остатка. Сумма
складывала сырьё и материал, уже прошедший участок, в одно число, тогда как
списание точное: `TRANSFER_SEND` со склада резолвит группу по маршруту
исходного задания и без строки с совпавшим признаком расход невозможен — даже
если склад суммарно полон (ADR-0055 п.3).

Проверяем:
- `available` считается по группе оси операций, а не по всему артикулу на складе;
- ответ несёт сам признак (`completed_operations`);
- число совпадает с тем, что видит write-guard выдачи
  (`compute_stock_section_transferable` для задания склада).
"""
from __future__ import annotations

from decimal import Decimal

import pytest
from app.stock.models import QualityState, Reason
from app.stock.services import StockCommand, StockCommandService
from app.transfers.transferable import compute_stock_section_transferable
from sqlalchemy.ext.asyncio import AsyncSession

from tests.helpers.completed_operations import build_operation_route, ops_through

pytestmark = pytest.mark.asyncio

STAGES = [
    ("Склад сырья", "raw_stock", ["ISSUE_RAW"]),
    ("Пресс", "production", ["PRESS_COMB"]),
]


async def _fixture(session: AsyncSession, sku: str) -> dict:
    return await build_operation_route(session, sku=sku, stages=STAGES)


async def _seed(
    session: AsyncSession,
    fx: dict,
    *,
    location_id: int,
    qty: str,
    ops: list[str] | None,
) -> None:
    await StockCommandService().record(
        session,
        StockCommand(
            product_id=fx["product"].id,
            to_location_id=location_id,
            quantity=Decimal(qty),
            reason=Reason.MANUAL_IN,
            quality_state=QualityState.GOOD,
            completed_operations=ops,
            created_by=fx["user"].id,
        ),
    )
    await session.commit()


async def test_available_counts_only_input_operations_group(client, session) -> None:
    """Остаток другого состояния на том же складе в «доступно» не попадает."""
    fx = await _fixture(session, "SPGAV-1")
    stock, prod = fx["sections"][0], fx["sections"][1]
    await _seed(session, fx, location_id=stock.id, qty="400", ops=ops_through(STAGES, 1))
    # Материал, уже прошедший пресс, и legacy-строка без признака: это ДРУГИЕ
    # остатки того же артикула на том же складе.
    await _seed(session, fx, location_id=stock.id, qty="900", ops=ops_through(STAGES, 2))
    await _seed(session, fx, location_id=stock.id, qty="5", ops=None)

    task = fx["tasks"][1]
    assert task.section_id == prod.id

    resp = await client.get(f"/api/shopfloor/tasks/{task.id}/spg-available")
    assert resp.status_code == 200, resp.text
    body = resp.json()

    assert body["location_id"] == stock.id
    assert body["completed_operations"] == ops_through(STAGES, 1) == ["ISSUE_RAW"]
    assert body["available"] == 400.0, body


async def test_available_matches_issuing_write_guard(client, session) -> None:
    """Число совпадает с физическим остатком группы в write-guard выдачи."""
    fx = await _fixture(session, "SPGAV-2")
    stock = fx["sections"][0]
    await _seed(session, fx, location_id=stock.id, qty="400", ops=ops_through(STAGES, 1))
    await _seed(session, fx, location_id=stock.id, qty="900", ops=ops_through(STAGES, 2))

    task = fx["tasks"][1]
    resp = await client.get(f"/api/shopfloor/tasks/{task.id}/spg-available")
    assert resp.status_code == 200, resp.text

    # Задание склада — тот самый отправитель, чей TRANSFER_SEND спишет остаток.
    stock_task = fx["tasks"][0]
    _transferable, _plan_remaining, physical_stock, _already = (
        await compute_stock_section_transferable(
            session,
            task=stock_task,
            section=stock,
            planned_qty=stock_task.planned_quantity,
        )
    )

    assert physical_stock == Decimal(400)
    assert resp.json()["available"] == float(physical_stock)


async def test_available_for_task_standing_on_stock_section(client, session) -> None:
    """Задание на самой складской секции читает группу своего же этапа."""
    fx = await _fixture(session, "SPGAV-3")
    stock = fx["sections"][0]
    await _seed(session, fx, location_id=stock.id, qty="400", ops=ops_through(STAGES, 1))
    await _seed(session, fx, location_id=stock.id, qty="900", ops=ops_through(STAGES, 2))

    stock_task = fx["tasks"][0]
    assert stock_task.section_id == stock.id

    resp = await client.get(f"/api/shopfloor/tasks/{stock_task.id}/spg-available")
    assert resp.status_code == 200, resp.text
    body = resp.json()

    assert body["location_id"] == stock.id
    assert body["completed_operations"] == ["ISSUE_RAW"]
    assert body["available"] == 400.0
