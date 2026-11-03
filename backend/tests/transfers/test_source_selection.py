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
from app.models.product import Product, ProductType
from app.models.section import Section
from app.services.product_alias_groups import AliasGroups
from app.stock.models import QualityState, StockBalance
from app.transfers.source_selection import build_issue_plan
from sqlalchemy.ext.asyncio import AsyncSession

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
    product_id: int | None = None,
) -> StockBalance:
    balance = StockBalance(
        product_id=product_id if product_id is not None else fx["product"].id,
        location_id=location.id,
        quality_state=quality,
        dimensions=dims,
        completed_operations=ops,
        balance_qty=Decimal(str(qty)),
    )
    session.add(balance)
    await session.flush()
    return balance


async def _equivalent(session: AsyncSession, fx: dict, sku: str) -> Product:
    """Эквивалент артикула задания: alias-ребро в одну сторону (#394)."""
    product = Product(
        sku=sku,
        name=sku,
        type=ProductType.component,
        unit="pcs",
        is_active=True,
    )
    session.add(product)
    await session.flush()
    fx["product"].aliases = [sku]
    await session.commit()
    return product


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


# ─── Общий пул эквивалентов (#393/#395) ────────────────────────────────────


async def test_equivalent_balance_becomes_candidate(session: AsyncSession):
    """Остаток эквивалента — такой же источник выдачи, как артикул задания."""
    fx = await _route(session, "SEL-EQ")
    stock1 = fx["sections"][0]
    equivalent = await _equivalent(session, fx, "SEL-EQ-B")

    balance = await _seed(
        session, fx, stock1, qty=50, ops=["STORE"], product_id=equivalent.id
    )

    plan = await _plan(session, fx, 30)

    assert [c.balance_id for c in plan.candidates] == [balance.id]
    candidate = plan.candidates[0]
    assert candidate.product_id == equivalent.id
    assert candidate.sku == equivalent.sku
    assert candidate.is_task_product is False
    assert candidate.group_key == min(fx["product"].id, equivalent.id)
    assert plan.group_key == min(fx["product"].id, equivalent.id)
    assert plan.group_skus == (fx["product"].sku, equivalent.sku)
    assert candidate.take == Decimal(30)
    assert plan.collected == Decimal(30)


async def test_task_product_is_exhausted_before_better_equivalent(
    session: AsyncSession,
):
    """Артикул задания — первый ключ даже против более близкого эквивалента."""
    fx = await _route(session, "SEL-TASKFIRST")
    stock1 = fx["sections"][0]
    extra = await _add_stock_section(session, "SEL-TASKFIRST-W", "Склад-3")
    equivalent = await _equivalent(session, fx, "SEL-TASKFIRST-B")

    task_balance = await _seed(session, fx, extra, qty=30, ops=["STORE"])  # цель 2
    equivalent_balance = await _seed(
        session, fx, stock1, qty=100, ops=["CUT", "STORE"], product_id=equivalent.id
    )  # цель 3 — ближе к адресату

    plan = await _plan(session, fx, 50)
    by_order = sorted(plan.candidates, key=lambda c: c.order)

    assert [c.balance_id for c in by_order] == [
        task_balance.id,
        equivalent_balance.id,
    ]
    assert by_order[0].is_task_product is True
    assert by_order[1].is_task_product is False
    assert [c.take for c in by_order] == [Decimal(30), Decimal(20)]


async def test_manual_selection_accepts_equivalent(session: AsyncSession):
    """Ручной выбор принимает остаток любого члена группы."""
    fx = await _route(session, "SEL-SEL-EQ")
    stock1 = fx["sections"][0]
    equivalent = await _equivalent(session, fx, "SEL-SEL-EQ-B")
    balance = await _seed(
        session, fx, stock1, qty=50, ops=["STORE"], product_id=equivalent.id
    )

    plan = await _plan(session, fx, 20, selected_balance_ids={balance.id})

    assert [c.balance_id for c in plan.candidates] == [balance.id]
    assert plan.candidates[0].take == Decimal(20)


async def test_manual_selection_rejects_foreign_product(session: AsyncSession):
    """Чужой артикул (вне группы) — отказ про группу эквивалентов."""
    fx = await _route(session, "SEL-SEL-FOREIGN")
    stock1 = fx["sections"][0]
    foreign = Product(
        sku="SEL-SEL-FOREIGN-X",
        name="foreign",
        type=ProductType.component,
        unit="pcs",
        is_active=True,
    )
    session.add(foreign)
    await session.flush()
    balance = await _seed(
        session, fx, stock1, qty=50, ops=["STORE"], product_id=foreign.id
    )

    with pytest.raises(ValueError, match="не из группы эквивалентов"):
        await _plan(session, fx, 20, selected_balance_ids={balance.id})


async def test_hints_count_equivalent_stock(session: AsyncSession):
    """Брак и чужой размер эквивалента — подсказка, а не источник."""
    fx = await _route(session, "SEL-EQ-HINTS")
    stock1 = fx["sections"][0]
    extra = await _add_stock_section(session, "SEL-EQ-HINTS-W", "Склад-И")
    equivalent = await _equivalent(session, fx, "SEL-EQ-HINTS-B")

    await _seed(session, fx, stock1, qty=150, ops=["STORE"])  # закрывает потребность
    await _seed(
        session, fx, extra, qty=10, ops=["STORE"], product_id=equivalent.id
    )  # включён, очередь не дошла
    await _seed(
        session, fx, extra, qty=20, ops=["STORE"], quality=QualityState.SCRAP,
        product_id=equivalent.id,
    )
    await _seed(
        session, fx, extra, qty=30, ops=["STORE"], dims=OTHER_DIM,
        product_id=equivalent.id,
    )

    plan = await _plan(session, fx, 100)

    kinds = {(h.kind, h.location_id) for h in plan.hints}
    assert kinds == {("defect", extra.id), ("other_size", extra.id)}
    defect = next(h for h in plan.hints if h.kind == "defect")
    other = next(h for h in plan.hints if h.kind == "other_size")
    assert defect.quantity == Decimal(20)
    assert other.quantity == Decimal(30)


async def test_group_of_one_keeps_previous_behaviour(session: AsyncSession):
    """Группа из одного продукта — прежние поля и порядок, только с ключом."""
    fx = await _route(session, "SEL-ONE")
    stock1 = fx["sections"][0]
    balance = await _seed(session, fx, stock1, qty=40, ops=["STORE"])

    plan = await _plan(session, fx, 20)

    assert plan.group_key == fx["product"].id
    assert plan.group_skus == (fx["product"].sku,)
    candidate = plan.candidates[0]
    assert candidate.balance_id == balance.id
    assert candidate.group_key == fx["product"].id
    assert candidate.product_id == fx["product"].id
    assert candidate.sku == fx["product"].sku
    assert candidate.is_task_product is True


async def test_unresolved_group_falls_back_to_single_product(
    session: AsyncSession,
):
    """Группа не резолвится — ведём себя как с группой из одного продукта."""
    fx = await _route(session, "SEL-NOGROUP")
    stock1 = fx["sections"][0]
    balance = await _seed(session, fx, stock1, qty=40, ops=["STORE"])

    plan = await build_issue_plan(
        session,
        position=fx["position"],
        product_id=fx["product"].id,
        required=Decimal(20),
        alias_groups=AliasGroups(()),
        group_ids=[fx["product"].id],
    )

    assert plan.group_key == fx["product"].id
    assert plan.group_skus == ()
    candidate = next(c for c in plan.candidates if c.balance_id == balance.id)
    assert candidate.sku is None
    assert candidate.is_task_product is True
