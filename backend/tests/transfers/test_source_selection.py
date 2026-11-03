"""Ядро автоподбора источника выдачи (``source_selection.build_issue_plan``).

Покрывает правило Q1/Q2 (#207, #282) без записи в ledger — подбор только
считает план:

- системный порядок кандидатов и поле ``order``;
- снятая галочка (``excluded_balance_ids``) живёт ровно один вызов;
- ``remaining_after``: ``Decimal(0)`` — склад вычерпан, ``None`` — прочерк;
- честный ``deficit`` при нехватке;
- источники — только GOOD: брак/переделка не вычерпываются;
- подсказки «брак»/«другой размер» только по включённым складам;
- нулевая потребность и пустой ключ (нечего брать).
"""
from __future__ import annotations

from decimal import Decimal

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.section import Section
from app.stock.models import QualityState, StockBalance
from app.transfers.source_selection import build_issue_plan
from tests.helpers.completed_operations import build_operation_route

DIM = {"length_mm": 2750}
OTHER_DIM = {"length_mm": 3000}

# Этап 1 — склад (STORE), этапы 2–3 — производство. Цели подбора:
# sequence 2 принимает признак ["STORE"], sequence 3 — ["CUT", "STORE"].
STAGES = [
    ("Склад-заготовка", "raw_stock", ["STORE"]),
    ("Цех-раскрой", "production", ["CUT"]),
    ("Цех-сверло", "production", ["DRILL"]),
]


async def _route(session: AsyncSession, sku: str) -> dict:
    return await build_operation_route(
        session, sku=sku, stages=STAGES, input_dimensions=DIM
    )


async def _add_stock_section(session: AsyncSession, code: str, name: str) -> Section:
    section = Section(code=code, name=name, type="wip_stock", is_active=True, sort_order=90)
    session.add(section)
    await session.flush()
    return section


async def _seed(
    session: AsyncSession,
    fx: dict,
    location: Section,
    *,
    qty: str | int,
    ops: list[str] | None,
    dims: dict | None = DIM,
    quality: QualityState = QualityState.GOOD,
) -> StockBalance:
    balance = StockBalance(
        product_id=fx["product"].id,
        location_id=location.id,
        quality_state=quality,
        dimensions=dims,
        completed_operations=ops,
        balance_qty=Decimal(str(qty)),
    )
    session.add(balance)
    await session.flush()
    return balance


async def _plan(session: AsyncSession, fx: dict, required, **kwargs):
    return await build_issue_plan(
        session,
        position=fx["position"],
        product_id=fx["product"].id,
        required=Decimal(str(required)),
        **kwargs,
    )


async def test_system_order_and_order_field(session: AsyncSession):
    """Ближайший назад по маршруту вычерпывается первым; ``order`` 0..N-1."""
    fx = await _route(session, "SEL-ORDER")
    stock1, _p1, _p2 = fx["sections"]
    extra = await _add_stock_section(session, "SEL-ORDER-W", "Склад-В")

    bal_a = await _seed(session, fx, stock1, qty=50, ops=["STORE"])       # цель 2
    bal_b = await _seed(session, fx, extra, qty=50, ops=["STORE"])        # цель 2, дальше по id склада
    bal_c = await _seed(session, fx, stock1, qty=30, ops=["CUT", "STORE"])  # цель 3 — ближе к адресату

    plan = await _plan(session, fx, 70)

    by_order = sorted(plan.candidates, key=lambda c: c.order)
    assert [c.balance_id for c in by_order] == [bal_c.id, bal_a.id, bal_b.id]
    assert [c.order for c in by_order] == [0, 1, 2]
    assert [c.target_sequence for c in by_order] == [3, 2, 2]
    # 30 из «Цех-сверло» + 40 из «Склад-заготовка»; третий склад не тронут.
    assert [c.take for c in by_order] == [Decimal(30), Decimal(40), Decimal(0)]
    assert [c.remaining_after for c in by_order] == [Decimal(0), Decimal(10), None]
    assert plan.collected == Decimal(70)
    assert plan.deficit == Decimal(0)


async def test_excluded_checkbox_lives_exactly_one_call(session: AsyncSession):
    """Снят галочкой склад не вычерпывается, но снятие живёт один вызов."""
    fx = await _route(session, "SEL-CHECK")
    stock1 = fx["sections"][0]
    extra = await _add_stock_section(session, "SEL-CHECK-W", "Склад-Г")

    bal_a = await _seed(session, fx, stock1, qty=40, ops=["STORE"])
    bal_b = await _seed(session, fx, extra, qty=40, ops=["STORE"])

    with_exclusion = await _plan(session, fx, 60, excluded_balance_ids={bal_a.id})
    by_id = {c.balance_id: c for c in with_exclusion.candidates}
    assert by_id[bal_a.id].included is False
    assert by_id[bal_a.id].take == Decimal(0)
    assert by_id[bal_a.id].remaining_after is None  # прочерк, не «вычерпан»
    assert by_id[bal_b.id].take == Decimal(40)
    # Один лишь склад Б не закрывает потребность — дефицит честный.
    assert with_exclusion.collected == Decimal(40)
    assert with_exclusion.deficit == Decimal(20)

    # То же окно, следующий вызов без параметра: галочка «вернулась» —
    # исключение не состояние модуля, а аргумент одного вызова.
    fresh = await _plan(session, fx, 60)
    by_id = {c.balance_id: c for c in fresh.candidates}
    assert by_id[bal_a.id].included is True
    assert by_id[bal_a.id].take == Decimal(40)
    assert fresh.deficit == Decimal(0)


async def test_remaining_after_zero_versus_dash(session: AsyncSession):
    """0 — склад вычерпан целиком; None — прочерк (очередь не дошла)."""
    fx = await _route(session, "SEL-REMAIN")
    stock1 = fx["sections"][0]
    extra = await _add_stock_section(session, "SEL-REMAIN-W", "Склад-Д")

    bal_a = await _seed(session, fx, stock1, qty=60, ops=["STORE"])
    bal_b = await _seed(session, fx, extra, qty=60, ops=["STORE"])

    plan = await _plan(session, fx, 60)
    by_id = {c.balance_id: c for c in plan.candidates}
    assert by_id[bal_a.id].remaining_after == Decimal(0)
    assert by_id[bal_a.id].take == Decimal(60)
    # Б не включён галочкой и очередь до него не дошла: включён, но прочерк.
    assert by_id[bal_b.id].included is True
    assert by_id[bal_b.id].take == Decimal(0)
    assert by_id[bal_b.id].remaining_after is None


async def test_deficit_when_stock_is_short(session: AsyncSession):
    """Перебраны все кандидаты — нехватка в ``deficit``, а не исключение."""
    fx = await _route(session, "SEL-DEFICIT")
    stock1 = fx["sections"][0]
    extra = await _add_stock_section(session, "SEL-DEFICIT-W", "Склад-Е")

    await _seed(session, fx, stock1, qty=10, ops=["STORE"])
    await _seed(session, fx, extra, qty=20, ops=["STORE"])

    plan = await _plan(session, fx, 60)
    assert plan.collected == Decimal(30)
    assert plan.deficit == Decimal(30)
    assert all(c.remaining_after == Decimal(0) for c in plan.candidates)


async def test_sources_are_good_only(session: AsyncSession):
    """Брак и переделка — не источник: вычерпывается только GOOD."""
    fx = await _route(session, "SEL-GOOD")
    stock1 = fx["sections"][0]

    good = await _seed(session, fx, stock1, qty=10, ops=["STORE"])
    await _seed(session, fx, stock1, qty=50, ops=["STORE"], quality=QualityState.SCRAP)
    await _seed(session, fx, stock1, qty=50, ops=["STORE"], quality=QualityState.REWORK)

    plan = await _plan(session, fx, 30)
    assert [c.balance_id for c in plan.candidates] == [good.id]
    assert plan.collected == Decimal(10)
    assert plan.deficit == Decimal(20)
    # REWORK подсказкой не считается, SCRAP — да и только по включённому складу.
    defect = [h for h in plan.hints if h.kind == "defect"]
    assert len(defect) == 1
    assert defect[0].quantity == Decimal(50)


async def test_hints_follow_included_warehouses(session: AsyncSession):
    """«брак»/«другой размер» — по включённым складам; снятая галочка гасит."""
    fx = await _route(session, "SEL-HINTS")
    stock1 = fx["sections"][0]
    extra = await _add_stock_section(session, "SEL-HINTS-W", "Склад-Ж")

    await _seed(session, fx, stock1, qty=150, ops=["STORE"])          # закрывает потребность
    bal_b = await _seed(session, fx, extra, qty=10, ops=["STORE"])    # включён, очередь не дошла
    await _seed(session, fx, extra, qty=20, ops=["STORE"], quality=QualityState.SCRAP)
    await _seed(session, fx, extra, qty=30, ops=["STORE"], dims=OTHER_DIM)

    plan = await _plan(session, fx, 100)
    kinds = {(h.kind, h.location_id) for h in plan.hints}
    assert kinds == {("defect", extra.id), ("other_size", extra.id)}
    other = next(h for h in plan.hints if h.kind == "other_size")
    assert other.dimensions == OTHER_DIM
    assert "2,75" in other.text  # нужная длина в подписи
    assert "браком" in next(h for h in plan.hints if h.kind == "defect").text

    # Сняли галочку со склада Ж — его брак и его чужой размер больше не аргумент.
    plan_excluded = await _plan(session, fx, 100, excluded_balance_ids={bal_b.id})
    cand_b = next(c for c in plan_excluded.candidates if c.balance_id == bal_b.id)
    assert cand_b.included is False
    assert all(h.location_id != extra.id for h in plan_excluded.hints)
    assert not plan_excluded.hints


async def test_zero_demand_is_noop(session: AsyncSession):
    """Нулевая потребность: никто не вычерпывается, дефицита нет."""
    fx = await _route(session, "SEL-ZERO")
    stock1 = fx["sections"][0]
    await _seed(session, fx, stock1, qty=40, ops=["STORE"])

    plan = await _plan(session, fx, 0)
    assert plan.collected == Decimal(0)
    assert plan.deficit == Decimal(0)
    assert all(c.take == Decimal(0) and c.remaining_after is None for c in plan.candidates)


@pytest.mark.parametrize("seed_negative", [False, True])
async def test_empty_stock_key_yields_no_candidates(session: AsyncSession, seed_negative: bool):
    """Нет строк баланса (или только минус) — кандидатов нет, дефицит = спросу."""
    fx = await _route(session, f"SEL-EMPTY-{'NEG' if seed_negative else 'NONE'}")
    stock1 = fx["sections"][0]
    if seed_negative:
        # Минус легален после negative_remainder; подбор в такой строку не ходит.
        await _seed(session, fx, stock1, qty=-5, ops=["STORE"])

    plan = await _plan(session, fx, 60)
    assert plan.candidates == ()
    assert plan.collected == Decimal(0)
    assert plan.deficit == Decimal(60)
    assert not plan.hints
