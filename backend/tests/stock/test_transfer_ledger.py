"""Consistency-тесты ledger-примитива stock/ledger (T1, #101; п.2 арх-ревью).

Проверяют, что все формы (scalar / grouped-by-dimensions / SQL-подзапрос)
построены на одном comp-aware builder'е ``net_quantity_expr()``: net по ЛЮБОЙ
причине с учётом компенсаций (``reverses_id``), ключи task_id /
section_plan_line_id, hash_key-конвенция dimension-grouping (как у
``app.stock.services``). Reason-параметризация (net_by_reason* / thin
wrappers) — публичные query-композиции над единственным семантическим
primitive (ADR-0017, ADR-0018).
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal

import pytest
import pytest_asyncio
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.internal_plan import InternalPlan, SectionPlanLine
from app.models.product import Product, ProductType
from app.models.production_plan import (
    PlanPosition,
    PlanPositionStatus,
    PlanPositionValidationStatus,
    PlanSourceType,
    ProductionPlan,
    ProductionPlanStatus,
)
from app.models.route import ProductionRoute, RouteStage
from app.models.section import Section
from app.models.user import User, UserRole
from app.models.work_task import WorkTask, WorkTaskStatus
from app.stock import Reason, StockCommand, StockCommandService
from app.stock import ledger as tl
from app.stock.services import _dimensions_hash_key
from tests.test_integrity_invariants import assert_no_invariants_violations

pytestmark = pytest.mark.asyncio

DIMS_2700 = {"length_mm": 2700}
DIMS_900 = {"length_mm": 900}


async def _make_fixture(session: AsyncSession) -> dict:
    """Минимальная топология: 2 секции, 2 строки плана, 2 задания, продукт."""
    user = User(email="ledger@local", full_name="Ledger Tester", role=UserRole.operator, is_active=True)
    session.add(user)
    await session.flush()

    sec1 = Section(code="LED-S1", name="S1", type="production", is_active=True, sort_order=0)
    sec2 = Section(code="LED-S2", name="S2", type="production", is_active=True, sort_order=1)
    session.add_all([sec1, sec2])
    await session.flush()

    product = Product(sku="LED-P", name="P", type=ProductType.finished_good, unit="pcs", is_active=True)
    session.add(product)
    await session.flush()

    route = ProductionRoute(name="R-LED", is_active=True)
    session.add(route)
    await session.flush()
    stage1 = RouteStage(route_id=route.id, sequence=1, section_id=sec1.id, is_final=False)
    stage2 = RouteStage(route_id=route.id, sequence=2, section_id=sec2.id, is_final=True)
    session.add_all([stage1, stage2])
    await session.flush()

    plan = ProductionPlan(
        plan_no="P-LED", name="p", status=ProductionPlanStatus.approved,
        period_start=date(2026, 5, 1), period_end=date(2026, 5, 31),
    )
    session.add(plan)
    await session.flush()

    pos = PlanPosition(
        production_plan_id=plan.id, product_id=product.id,
        source_type=PlanSourceType.manual, source_sku=product.sku, source_name=product.name,
        quantity=Decimal("100"), source_payload={}, status=PlanPositionStatus.approved,
        validation_status=PlanPositionValidationStatus.valid, validation_errors=[],
        period_start=plan.period_start, period_end=plan.period_end,
        has_pack_ops=False, route_id=route.id, route_assigned_at=None,
    )
    session.add(pos)
    await session.flush()

    internal = InternalPlan(production_plan_id=plan.id)
    session.add(internal)
    await session.flush()

    line1 = SectionPlanLine(
        internal_plan_id=internal.id, plan_position_id=pos.id, section_id=sec1.id,
        product_id=product.id, route_id=route.id, route_stage_id=stage1.id,
        sequence=1, planned_quantity=Decimal("100"),
    )
    line2 = SectionPlanLine(
        internal_plan_id=internal.id, plan_position_id=pos.id, section_id=sec2.id,
        product_id=product.id, route_id=route.id, route_stage_id=stage2.id,
        sequence=2, planned_quantity=Decimal("100"),
    )
    session.add_all([line1, line2])
    await session.flush()

    task1 = WorkTask(
        section_plan_line_id=line1.id, section_id=sec1.id, product_id=product.id,
        route_stage_id=stage1.id, planned_quantity=Decimal("100"), status=WorkTaskStatus.ready,
    )
    task2 = WorkTask(
        section_plan_line_id=line2.id, section_id=sec2.id, product_id=product.id,
        route_stage_id=stage2.id, planned_quantity=Decimal("100"), status=WorkTaskStatus.ready,
    )
    session.add_all([task1, task2])
    await session.commit()

    return {
        "user": user, "product": product, "sections": [sec1, sec2],
        "lines": [line1, line2], "tasks": [task1, task2],
    }


async def _record(
    session: AsyncSession,
    *,
    user_id: int,
    product_id: int,
    reason: Reason,
    quantity: Decimal,
    task_id: int,
    line_id: int,
    location_id: int,
    dims: dict | None,
    reverses_id: int | None = None,
):
    """Одна запись ledger через StockCommandService (проекции обновляются).

    Компенсация зеркалит локации исходной проводки (from/to переворачиваются),
    чтобы баланс оставался консистентным (инвариант S1).
    """
    svc = StockCommandService()
    if reverses_id is not None:
        from_location_id, to_location_id = location_id, None
    else:
        from_location_id, to_location_id = None, location_id
    return await svc.record(
        session,
        StockCommand(
            product_id=product_id,
            from_location_id=from_location_id,
            to_location_id=to_location_id,
            quantity=quantity,
            reason=reason,
            dimensions=dims,
            task_id=task_id,
            section_plan_line_id=line_id,
            reverses_id=reverses_id,
            created_by=user_id,
        ),
    )


async def _seed_ledger(session: AsyncSession, fx: dict) -> None:
    """SEND/RECEIVE по (task1/line1, task2/line2) с группами габаритов и
    компенсациями.

    net TRANSFER_SEND   task1: {2700: 10-10=0, 900: 5, None: 3}, total 8; task2: {2700: 7}.
    net TRANSFER_RECEIVE task1: {2700: 12-12=0, None: 4};              task2: {900: 6}.
    """
    user_id = fx["user"].id
    product_id = fx["product"].id
    task1, task2 = fx["tasks"]
    line1, line2 = fx["lines"]
    sec1, sec2 = fx["sections"]

    send1 = await _record(
        session, user_id=user_id, product_id=product_id, reason=Reason.TRANSFER_SEND,
        quantity=Decimal("10"), task_id=task1.id, line_id=line1.id,
        location_id=sec1.id, dims=DIMS_2700,
    )
    await _record(
        session, user_id=user_id, product_id=product_id, reason=Reason.TRANSFER_SEND,
        quantity=Decimal("10"), task_id=task1.id, line_id=line1.id,
        location_id=sec1.id, dims=DIMS_2700, reverses_id=send1.id,
    )
    await _record(
        session, user_id=user_id, product_id=product_id, reason=Reason.TRANSFER_SEND,
        quantity=Decimal("5"), task_id=task1.id, line_id=line1.id,
        location_id=sec1.id, dims=DIMS_900,
    )
    await _record(
        session, user_id=user_id, product_id=product_id, reason=Reason.TRANSFER_SEND,
        quantity=Decimal("3"), task_id=task1.id, line_id=line1.id,
        location_id=sec1.id, dims=None,
    )
    await _record(
        session, user_id=user_id, product_id=product_id, reason=Reason.TRANSFER_SEND,
        quantity=Decimal("7"), task_id=task2.id, line_id=line2.id,
        location_id=sec2.id, dims=DIMS_2700,
    )

    recv1 = await _record(
        session, user_id=user_id, product_id=product_id, reason=Reason.TRANSFER_RECEIVE,
        quantity=Decimal("12"), task_id=task1.id, line_id=line1.id,
        location_id=sec1.id, dims=DIMS_2700,
    )
    await _record(
        session, user_id=user_id, product_id=product_id, reason=Reason.TRANSFER_RECEIVE,
        quantity=Decimal("12"), task_id=task1.id, line_id=line1.id,
        location_id=sec1.id, dims=DIMS_2700, reverses_id=recv1.id,
    )
    await _record(
        session, user_id=user_id, product_id=product_id, reason=Reason.TRANSFER_RECEIVE,
        quantity=Decimal("4"), task_id=task1.id, line_id=line1.id,
        location_id=sec1.id, dims=None,
    )
    await _record(
        session, user_id=user_id, product_id=product_id, reason=Reason.TRANSFER_RECEIVE,
        quantity=Decimal("6"), task_id=task2.id, line_id=line2.id,
        location_id=sec2.id, dims=DIMS_900,
    )
    await session.commit()
    await assert_no_invariants_violations(session, context="transfer-ledger")


@pytest_asyncio.fixture
async def ledger_fx(session: AsyncSession) -> dict:
    fx = await _make_fixture(session)
    await _seed_ledger(session, fx)
    return fx


async def _sq_value(session: AsyncSession, sq, where_col, key: int) -> Decimal:
    """SQL-форма: net по ключу из grouped-подзапроса (как set-based потребитель)."""
    row = await session.execute(
        select(sq.c.net_quantity).select_from(sq).where(where_col == key)
    )
    return row.scalar_one()


async def test_scalar_equals_sql_by_task_id(session: AsyncSession, ledger_fx: dict) -> None:
    """scalar net_transferred(task_id, dims) == grouped SQL-подзапрос (компенсация!)."""
    task1 = ledger_fx["tasks"][0]

    scalar = await tl.net_transferred(session, task_id=task1.id, dims=DIMS_2700)
    sq = tl.net_transferred_sq(alias="ledger_send_2700", dims=DIMS_2700)
    sql_value = await _sq_value(session, sq, sq.c.task_id, task1.id)
    # компенсированная строка вычитается: 10 - 10 == 0
    assert scalar == sql_value == Decimal("0")

    scalar_900 = await tl.net_transferred(session, task_id=task1.id, dims=DIMS_900)
    sq_900 = tl.net_transferred_sq(alias="ledger_send_900", dims=DIMS_900)
    sql_900 = await _sq_value(session, sq_900, sq_900.c.task_id, task1.id)
    assert scalar_900 == sql_900 == Decimal("5")

    # SQL-форма без dims = total по ключу (dims=None → без dimension-фильтра)
    sq_all = tl.net_transferred_sq(alias="ledger_send_all")
    sql_all = await _sq_value(session, sq_all, sq_all.c.task_id, task1.id)
    assert sql_all == Decimal("8")


async def test_scalar_equals_sql_by_section_plan_line_id(
    session: AsyncSession, ledger_fx: dict
) -> None:
    """scalar net_transferred(section_plan_line_id, dims) == SQL-подзапрос по линии."""
    line1, line2 = ledger_fx["lines"]

    scalar = await tl.net_transferred(session, section_plan_line_id=line1.id, dims=DIMS_2700)
    sq = tl.net_transferred_sq(
        alias="ledger_line", task_id=False, section_plan_line_id=True, dims=DIMS_2700
    )
    sql_value = await _sq_value(session, sq, sq.c.section_plan_line_id, line1.id)
    assert scalar == sql_value == Decimal("0")

    sq_all = tl.net_transferred_sq(
        alias="ledger_line_all", task_id=False, section_plan_line_id=True
    )
    sql_line1 = await _sq_value(session, sq_all, sq_all.c.section_plan_line_id, line1.id)
    sql_line2 = await _sq_value(session, sq_all, sq_all.c.section_plan_line_id, line2.id)
    assert sql_line1 == Decimal("8")
    assert sql_line2 == Decimal("7")


async def test_grouped_matches_scalars_per_dimension(
    session: AsyncSession, ledger_fx: dict
) -> None:
    """net_transferred_by_dimensions == {hash_key: scalar} для всех групп,
    включая безразмерную (ключ None)."""
    task1 = ledger_fx["tasks"][0]

    grouped = await tl.net_transferred_by_dimensions(session, task_id=task1.id)
    expected = {}
    for dims in [DIMS_2700, DIMS_900, None]:
        expected[_dimensions_hash_key(dims)] = await tl.net_transferred(
            session, task_id=task1.id, dims=dims
        )
    assert grouped == expected
    # NULL-группа (строки без dimensions) представлена ключом None
    assert grouped[None] == Decimal("3")
    # total по ключу == сумма групп
    assert sum(grouped.values(), Decimal("0")) == Decimal("8")


async def test_empty_returns_zero(session: AsyncSession) -> None:
    """Пусто (нет транзакций) → Decimal("0") / пустой dict."""
    fx = await _make_fixture(session)
    task1, task2 = fx["tasks"]
    line1, line2 = fx["lines"]

    assert await tl.net_transferred(session, task_id=task1.id) == Decimal("0")
    assert await tl.net_by_reason(
        session, reason=Reason.TRANSFER_RECEIVE, task_id=task1.id, dims=None
    ) == Decimal("0")
    assert await tl.net_transferred(
        session, section_plan_line_id=line1.id, dims=DIMS_2700
    ) == Decimal("0")
    assert await tl.net_by_reason(
        session, reason=Reason.TRANSFER_RECEIVE, task_id=task2.id, dims=DIMS_900
    ) == Decimal("0")
    assert await tl.net_transferred_by_dimensions(session, task_id=task1.id) == {}
    assert await tl.net_by_reason_by_dimensions(
        session, reason=Reason.TRANSFER_RECEIVE, task_id=task1.id
    ) == {}


async def test_exactly_one_key_required(session: AsyncSession, ledger_fx: dict) -> None:
    """Ровно один ключ (task_id XOR section_plan_line_id) обязателен."""
    with pytest.raises(ValueError):
        await tl.net_transferred(session)
    with pytest.raises(ValueError):
        await tl.net_transferred(session, task_id=1, section_plan_line_id=1)
    with pytest.raises(ValueError):
        await tl.net_by_reason(session, reason=Reason.TRANSFER_RECEIVE)
    with pytest.raises(ValueError):
        await tl.net_transferred_by_dimensions(session)
    with pytest.raises(ValueError):
        tl.net_transferred_sq(task_id=True, section_plan_line_id=True)
    with pytest.raises(ValueError):
        tl.net_received_sq(task_id=False, section_plan_line_id=False)


async def test_net_by_reason_final_release_compensation(session: AsyncSession) -> None:
    """net_by_reason(FINAL_RELEASE): net == gross без компенсаций; компенсация
    ВЫЧИТАЕТСЯ (не исключается) → net = 0. Reason-agnostic контракт (ADR-0017)."""
    fx = await _make_fixture(session)
    task2 = fx["tasks"][1]  # финальный этап (stage2.is_final=True)
    line2 = fx["lines"][1]
    sec2 = fx["sections"][1]
    user_id = fx["user"].id
    product_id = fx["product"].id

    # скаляр dims=None = безразмерная группа (не total), поэтому dims явный
    assert await tl.net_by_reason(
        session, reason=Reason.FINAL_RELEASE, task_id=task2.id, dims=DIMS_2700
    ) == Decimal("0")

    rel1 = await _record(
        session, user_id=user_id, product_id=product_id, reason=Reason.FINAL_RELEASE,
        quantity=Decimal("10"), task_id=task2.id, line_id=line2.id,
        location_id=sec2.id, dims=DIMS_2700,
    )
    assert await tl.net_by_reason(
        session, reason=Reason.FINAL_RELEASE, task_id=task2.id, dims=DIMS_2700
    ) == Decimal("10")

    await _record(
        session, user_id=user_id, product_id=product_id, reason=Reason.FINAL_RELEASE,
        quantity=Decimal("10"), task_id=task2.id, line_id=line2.id,
        location_id=sec2.id, dims=DIMS_2700, reverses_id=rel1.id,
    )
    await session.commit()
    # вычитается, а не исключается: 10 - 10 == 0 (не 10)
    assert await tl.net_by_reason(
        session, reason=Reason.FINAL_RELEASE, task_id=task2.id, dims=DIMS_2700
    ) == Decimal("0")


async def test_net_by_reason_by_dimensions_final_release(session: AsyncSession) -> None:
    """net_by_reason_by_dimensions(FINAL_RELEASE): группировка по габаритам, NULL-группа,
    сумма групп == total по ключу."""
    fx = await _make_fixture(session)
    task2 = fx["tasks"][1]
    line2 = fx["lines"][1]
    sec2 = fx["sections"][1]
    user_id = fx["user"].id
    product_id = fx["product"].id

    await _record(
        session, user_id=user_id, product_id=product_id, reason=Reason.FINAL_RELEASE,
        quantity=Decimal("10"), task_id=task2.id, line_id=line2.id,
        location_id=sec2.id, dims=DIMS_2700,
    )
    await _record(
        session, user_id=user_id, product_id=product_id, reason=Reason.FINAL_RELEASE,
        quantity=Decimal("3"), task_id=task2.id, line_id=line2.id,
        location_id=sec2.id, dims=None,
    )
    await session.commit()

    grouped = await tl.net_by_reason_by_dimensions(
        session, reason=Reason.FINAL_RELEASE, task_id=task2.id
    )
    assert grouped == {
        _dimensions_hash_key(DIMS_2700): Decimal("10"),
        None: Decimal("3"),
    }
    assert sum(grouped.values(), Decimal("0")) == Decimal("13")


async def test_net_by_reason_reason_separation(session: AsyncSession, ledger_fx: dict) -> None:
    """FINAL_RELEASE не попадает в net SEND/RECEIVE и наоборот (причина — фильтр, а
    не семантика)."""
    task2 = ledger_fx["tasks"][1]
    line2 = ledger_fx["lines"][1]
    sec2 = ledger_fx["sections"][1]
    user_id = ledger_fx["user"].id
    product_id = ledger_fx["product"].id

    before = await tl.net_transferred(session, task_id=task2.id, dims=DIMS_2700)
    before_recv = await tl.net_by_reason(
        session, reason=Reason.TRANSFER_RECEIVE, task_id=task2.id, dims=DIMS_900
    )

    await _record(
        session, user_id=user_id, product_id=product_id, reason=Reason.FINAL_RELEASE,
        quantity=Decimal("7"), task_id=task2.id, line_id=line2.id,
        location_id=sec2.id, dims=DIMS_2700,
    )
    await session.commit()

    assert await tl.net_transferred(session, task_id=task2.id, dims=DIMS_2700) == before
    assert await tl.net_by_reason(
        session, reason=Reason.TRANSFER_RECEIVE, task_id=task2.id, dims=DIMS_900
    ) == before_recv
    assert await tl.net_by_reason(
        session, reason=Reason.FINAL_RELEASE, task_id=task2.id, dims=DIMS_2700
    ) == Decimal("7")
