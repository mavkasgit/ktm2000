"""Ось «пройденные операции» в сводке артикула (ADR-0055, #236).

`GET /api/production-planning/product-wip-stats/{sku}` группировал строки
остатка по `(СПГ, название участка, габарит)`, а подписью строки печатал имя
участка. Операции — пятая ось ключа `stock_balances` (ADR-0055), поэтому два
разных остатка одного артикула на ОДНОМ участке с ОДНИМ габаритом сливались в
одну сумму — ровно дефект `13388` вместо `8888 + 4500`, ради которого ADR и
принят.

Проверяем:
- две ops-группы одного артикула/участка/габарита — две строки, не одна сумма;
- `NULL` («не зафиксировано») и `[]` («без операций») — разные строки;
- строка несёт ДАННЫЕ оси: `completed_operations` (признак) и
  `completed_stages` (этапы справочника в порядке маршрута); подпись состояния
  печатает клиент по общему правилу, сервер текст не дублирует (#242);
- одинаковые операции и габарит по-прежнему складываются в одну строку.
"""
from __future__ import annotations

from decimal import Decimal

import pytest
from app.models.route import SectionOperation
from app.models.section import Section
from app.stock.models import QualityState, Reason
from app.stock.services import StockCommand, StockCommandService
from sqlalchemy import update
from sqlalchemy.ext.asyncio import AsyncSession

from tests.helpers.completed_operations import build_operation_route, ops_through

pytestmark = pytest.mark.asyncio

STAGES = [
    ("Склад сырья", "raw_stock", ["ISSUE_RAW"]),
    ("Пресс", "production", ["PRESS_COMB"]),
]

# Человекочитаемые имена отличаются от кодов: подпись обязана собираться из
# справочника, а не печатать operation_code или название участка.
OP_NAMES = {"ISSUE_RAW": "Выдача сырья", "PRESS_COMB": "Пресс комбинированный"}

DIMS = {"length_mm": 2700}


async def _fixture(session: AsyncSession, sku: str) -> dict:
    """Маршрут «склад → пресс» с операциями секций, позицией плана и заданиями."""
    fx = await build_operation_route(session, sku=sku, stages=STAGES)
    for section in fx["sections"]:
        for code, name in OP_NAMES.items():
            await session.execute(
                update(SectionOperation)
                .where(
                    SectionOperation.section_id == section.id,
                    SectionOperation.operation_code == code,
                )
                .values(operation_name=name)
            )
    await session.commit()
    return fx


async def _seed(
    session: AsyncSession,
    fx: dict,
    *,
    stock: Section,
    qty: str,
    ops: list[str] | None,
) -> None:
    """Приход на складскую секцию в явной ops-группе (ADR-0055)."""
    await StockCommandService().record(
        session,
        StockCommand(
            product_id=fx["product"].id,
            to_location_id=stock.id,
            quantity=Decimal(qty),
            reason=Reason.MANUAL_IN,
            quality_state=QualityState.GOOD,
            dimensions=DIMS,
            completed_operations=ops,
            created_by=fx["user"].id,
        ),
    )
    await session.commit()


async def test_remainders_split_by_completed_operations(client, session) -> None:
    """Две ops-группы одного артикула и габарита — две строки, не одна сумма."""
    fx = await _fixture(session, "WIP-OPS-1")
    stock = fx["sections"][0]
    await _seed(
        session, fx, stock=stock, qty="100", ops=ops_through(STAGES, 1)
    )
    await _seed(
        session, fx, stock=stock, qty="40", ops=ops_through(STAGES, 2)
    )

    resp = await client.get(f"/api/production-planning/product-wip-stats/{fx['product'].sku}")
    assert resp.status_code == 200, resp.text
    rows = resp.json()["remainders"]

    assert len(rows) == 2, [
        (r["completed_operations"], r["quantity"]) for r in rows
    ]
    by_ops = {tuple(r["completed_operations"]): r for r in rows}
    assert by_ops[("ISSUE_RAW",)]["quantity"] == 100.0
    assert by_ops[("ISSUE_RAW", "PRESS_COMB")]["quantity"] == 40.0
    # Разделение идёт по оси, а не по участку или габариту: у обеих строк
    # одно и то же ГХП и один и тот же размер.
    assert len({r["spg_name"] for r in rows}) == 1
    assert len({r["dimensions_label"] for r in rows}) == 1
    assert {r["dimensions"]["length_mm"] for r in rows} == {2700}


async def test_remainder_stages_come_from_operations_dictionary(client, session) -> None:
    """Строка несёт этапы оси из справочника: коды и имена в порядке маршрута."""
    fx = await _fixture(session, "WIP-OPS-2")
    stock = fx["sections"][0]
    await _seed(session, fx, stock=stock, qty="7", ops=ops_through(STAGES, 2))

    resp = await client.get(f"/api/production-planning/product-wip-stats/{fx['product'].sku}")
    assert resp.status_code == 200, resp.text
    rows = resp.json()["remainders"]

    assert len(rows) == 1
    row = rows[0]
    assert row["completed_operations"] == ["ISSUE_RAW", "PRESS_COMB"]
    assert [
        (stage["operation_code"], stage["operation_name"])
        for stage in row["completed_stages"]
    ] == [("ISSUE_RAW", "Выдача сырья"), ("PRESS_COMB", "Пресс комбинированный")]
    # Клиент печатает имена, а не коды: текст подписи сервер не считает (#242).


async def test_remainders_distinguish_null_and_empty_operations(client, session) -> None:
    """`NULL` («не зафиксировано») и `[]` («без операций») — разные строки остатка."""
    fx = await _fixture(session, "WIP-OPS-3")
    stock = fx["sections"][0]
    await _seed(session, fx, stock=stock, qty="11", ops=None)
    await _seed(session, fx, stock=stock, qty="3", ops=[])

    resp = await client.get(f"/api/production-planning/product-wip-stats/{fx['product'].sku}")
    assert resp.status_code == 200, resp.text
    rows = resp.json()["remainders"]

    assert len(rows) == 2
    by_ops = {
        (tuple(r["completed_operations"]) if r["completed_operations"] is not None else None): r
        for r in rows
    }
    assert set(by_ops) == {None, ()}
    # Состояние уходит признаком, а не текстом: `null` и `[]` клиент
    # различает сам и печатает по общему правилу (#242).
    assert by_ops[None]["completed_operations"] is None
    assert by_ops[None]["completed_stages"] == []
    assert by_ops[()]["completed_operations"] == []
    assert by_ops[()]["completed_stages"] == []
    assert by_ops[()]["quantity"] == 3.0


async def test_remainders_merge_same_operations_and_dimensions(client, session) -> None:
    """Одинаковые операции и габарит на одной секции складываются в одну строку."""
    fx = await _fixture(session, "WIP-OPS-4")
    stock = fx["sections"][0]
    await _seed(session, fx, stock=stock, qty="60", ops=ops_through(STAGES, 1))
    await _seed(session, fx, stock=stock, qty="40", ops=ops_through(STAGES, 1))

    resp = await client.get(f"/api/production-planning/product-wip-stats/{fx['product'].sku}")
    assert resp.status_code == 200, resp.text
    rows = resp.json()["remainders"]

    assert len(rows) == 1
    assert rows[0]["quantity"] == 100.0
    assert rows[0]["completed_operations"] == ["ISSUE_RAW"]
    assert [stage["operation_name"] for stage in rows[0]["completed_stages"]] == [
        "Выдача сырья"
    ]
