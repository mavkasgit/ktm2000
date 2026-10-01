"""Индикатор остатка позиции: три числа с тремя именами (тикет #207).

Контракт: спрос считается ОДИН раз агрегатом по всем запущенным позициям,
а «свой» спрос позиции вычитается из него. Отсюда всё остальное:

* позиция не вычитает сама себя (ЮП-460: было ``1500 − 1512``);
* чужая открытая позиция того же артикула видна — и видна асимметрично:
  чем больше позиция, тем меньше остатка она оставляет соседней;
* позиция, которой ещё нет в спросе (не released), остаток не увеличивает;
* брак не источник: ``scrap`` вне обоих чисел, ``raw_stock`` внутри;
* дефицит = ``max(0, quantity − available)``;
* «нет данных» (``None``) и «действительно ноль`` (``0.0``) — разные вещи;
* список строк и карточка позиции отдают одни и те же три числа.
"""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal

import pytest
from app.models.internal_plan import InternalPlan, SectionPlanLine
from app.models.production_plan import (
    PlanPosition,
    PlanPositionRouteOrigin,
    PlanPositionStatus,
    PlanPositionValidationStatus,
    PlanSourceType,
    ProductionPlan,
)
from app.models.route import ProductionRoute, RouteStage
from app.models.section import Section
from app.models.work_task import WorkTask, WorkTaskStatus
from app.stock import Reason, StockCommand, StockCommandService
from sqlalchemy.ext.asyncio import AsyncSession

from tests.helpers.completed_operations import (
    build_plan as _make_plan,
)
from tests.helpers.completed_operations import (
    build_product as _make_product,
)
from tests.helpers.completed_operations import (
    build_stock_to_shop_route as _make_route,
)

pytestmark = pytest.mark.asyncio


async def _make_section(session: AsyncSession, *, code: str, type_: str, order: int) -> Section:
    section = Section(code=code, name=code, type=type_, is_active=True, sort_order=order)
    session.add(section)
    await session.flush()
    return section




async def _seed_good_balance(
    session: AsyncSession, *, location_id: int, product_id: int, qty: int
) -> None:
    """Физический GOOD-остаток артикула в указанной секции."""
    await StockCommandService().record(
        session,
        StockCommand(
            product_id=product_id,
            to_location_id=location_id,
            quantity=Decimal(qty),
            reason=Reason.MANUAL_IN,
            created_by=1,
        ),
    )
    await session.commit()


async def _add_position(
    session: AsyncSession,
    *,
    plan: ProductionPlan,
    route: ProductionRoute | None,
    stages: list[RouteStage],
    prod_section: Section,
    source_sku: str,
    product_id: int | None,
    quantity: Decimal,
    source_payload: dict | None = None,
    line_product_id: int | None = None,
    status: PlanPositionStatus = PlanPositionStatus.approved,
    task_status: WorkTaskStatus | None = WorkTaskStatus.ready,
) -> PlanPosition:
    """Позиция плана с маршрутом и её активная задача (``route=None`` — без маршрута)."""
    position = PlanPosition(
        production_plan_id=plan.id,
        product_id=product_id,
        source_type=PlanSourceType.excel_import,
        source_sku=source_sku,
        source_name=source_sku,
        quantity=quantity,
        source_payload=source_payload or {},
        status=status,
        validation_status=PlanPositionValidationStatus.valid,
        validation_errors=[],
        route_id=route.id if route is not None else None,
        route_origin=PlanPositionRouteOrigin.manual_confirmed if route is not None else None,
        route_assigned_at=datetime.now(UTC) if route is not None else None,
        route_manual_confirmed_at=datetime.now(UTC) if route is not None else None,
    )
    session.add(position)
    await session.flush()

    if route is not None:
        internal = InternalPlan(production_plan_id=plan.id)
        session.add(internal)
        await session.flush()

        line = SectionPlanLine(
            internal_plan_id=internal.id,
            plan_position_id=position.id,
            section_id=prod_section.id,
            product_id=line_product_id if line_product_id is not None else product_id,
            route_id=route.id,
            route_stage_id=stages[1].id,
            sequence=1,
            planned_quantity=quantity,
        )
        session.add(line)
        await session.flush()

        if task_status is not None:
            session.add(
                WorkTask(
                    section_plan_line_id=line.id,
                    section_id=prod_section.id,
                    product_id=line.product_id,
                    route_stage_id=stages[1].id,
                    planned_quantity=quantity,
                    status=task_status,
                )
            )
    await session.commit()
    return position


async def _rows_by_id(client) -> dict[int, dict]:
    resp = await client.get("/api/production-planning/rows?limit=500")
    assert resp.status_code == 200, resp.text
    return {row["plan_position_id"]: row for row in resp.json()["rows"]}


async def _detail(client, position_id: int) -> dict:
    resp = await client.get(f"/api/production-planning/rows/{position_id}")
    assert resp.status_code == 200, resp.text
    return resp.json()


async def test_indicator_does_not_subtract_the_position_own_demand(
    client, session: AsyncSession
) -> None:
    """ЮП-460: у запущенной позиции «Доступно» равно всему свободному остатку.

    Остаток 1500, позиция released на 1512 шт. со своей открытой задачей —
    весь спрос 1512 принадлежит ей самой, значит чужих ноль. Раньше было
    ``1500 − 1512 = −12`` и индикатор показывал 0 почти у каждой запущенной
    позиции.
    """
    product = await _make_product(session, sku="IND-SELF")
    stock, prod, route, stages = await _make_route(session, prefix="IND-SELF")
    plan = await _make_plan(session, prefix="IND-SELF")
    await _seed_good_balance(session, location_id=stock.id, product_id=product.id, qty=1500)

    position = await _add_position(
        session,
        plan=plan,
        route=route,
        stages=stages,
        prod_section=prod,
        source_sku=product.sku,
        product_id=product.id,
        quantity=Decimal(1512),
        status=PlanPositionStatus.released,
    )

    row = (await _rows_by_id(client))[position.id]
    assert row["free_stock_quantity"] == 1500.0
    assert row["available_remainder_quantity"] == 1500.0


async def test_other_open_position_lowers_available_but_not_free_stock(
    client, session: AsyncSession
) -> None:
    """Две released-позиции одного артикула видят друг друга — асимметрично.

    Свободно 2000. A=1500 и B=400, обе released с открытым заданием, общий
    спрос 1900. Из него вычитается спрос самой позиции: A оставляет B
    ``1900 − 1500 = 400``, B оставляет A ``1900 − 400 = 1500``. Свободно на
    складах у обеих 2000 — это свойство склада, а не пары позиций.
    """
    product = await _make_product(session, sku="IND-OTHER")
    stock, prod, route, stages = await _make_route(session, prefix="IND-OTHER")
    plan = await _make_plan(session, prefix="IND-OTHER")
    await _seed_good_balance(session, location_id=stock.id, product_id=product.id, qty=2000)

    big = await _add_position(
        session,
        plan=plan,
        route=route,
        stages=stages,
        prod_section=prod,
        source_sku=product.sku,
        product_id=product.id,
        quantity=Decimal(1500),
        status=PlanPositionStatus.released,
    )
    small = await _add_position(
        session,
        plan=plan,
        route=route,
        stages=stages,
        prod_section=prod,
        source_sku=product.sku,
        product_id=product.id,
        quantity=Decimal(400),
        status=PlanPositionStatus.released,
    )

    rows = await _rows_by_id(client)
    assert rows[big.id]["free_stock_quantity"] == 2000.0
    assert rows[big.id]["available_remainder_quantity"] == 1600.0
    assert rows[small.id]["free_stock_quantity"] == 2000.0
    assert rows[small.id]["available_remainder_quantity"] == 500.0

    assert (await _detail(client, big.id))["available_remainder_quantity"] == 1600.0
    assert (await _detail(client, small.id))["available_remainder_quantity"] == 500.0


async def test_position_outside_the_demand_does_not_increase_available_stock(
    client, session: AsyncSession
) -> None:
    """Позиция, которой ещё нет в спросе, доступный остаток не увеличивает.

    Свободно 1500, released-позиция B=300 — весь спрос 300. Позиция A=500
    ещё approved и в спросе не значится: её «свой спрос» не может прибавить
    к остатку, доступно те же 1500 (а не 1700).
    """
    product = await _make_product(session, sku="IND-CLAMP")
    stock, prod, route, stages = await _make_route(session, prefix="IND-CLAMP")
    plan = await _make_plan(session, prefix="IND-CLAMP")
    await _seed_good_balance(session, location_id=stock.id, product_id=product.id, qty=1500)

    not_started = await _add_position(
        session,
        plan=plan,
        route=route,
        stages=stages,
        prod_section=prod,
        source_sku=product.sku,
        product_id=product.id,
        quantity=Decimal(500),
    )
    released = await _add_position(
        session,
        plan=plan,
        route=route,
        stages=stages,
        prod_section=prod,
        source_sku=product.sku,
        product_id=product.id,
        quantity=Decimal(300),
        status=PlanPositionStatus.released,
    )

    rows = await _rows_by_id(client)
    assert rows[not_started.id]["free_stock_quantity"] == 1500.0
    assert rows[not_started.id]["available_remainder_quantity"] == 1500.0
    assert (await _detail(client, not_started.id))["available_remainder_quantity"] == 1500.0
    assert rows[released.id]["available_remainder_quantity"] == 1500.0


async def test_scrap_balance_is_excluded_and_raw_stock_is_included(
    client, session: AsyncSession
) -> None:
    """Брак не источник: ``scrap`` вне обоих чисел, ``raw_stock`` внутри.

    raw_stock 1000 + scrap 500, общий спрос двух released-позиций 500
    (200 + 300). Свободно 1000 (брак не прибавляется), доступно 700 и 800.
    Если бы брак попал в остаток, свободно было бы 1500, а доступно 1200 и 1300.
    """
    product = await _make_product(session, sku="IND-SCRAP")
    stock, prod, route, stages = await _make_route(session, prefix="IND-SCRAP")
    scrap = await _make_section(session, code="IND-SCRAP-SCR", type_="scrap", order=2)
    plan = await _make_plan(session, prefix="IND-SCRAP")

    await _seed_good_balance(session, location_id=stock.id, product_id=product.id, qty=1000)
    await _seed_good_balance(session, location_id=scrap.id, product_id=product.id, qty=500)

    first = await _add_position(
        session,
        plan=plan,
        route=route,
        stages=stages,
        prod_section=prod,
        source_sku=product.sku,
        product_id=product.id,
        quantity=Decimal(200),
        status=PlanPositionStatus.released,
    )
    second = await _add_position(
        session,
        plan=plan,
        route=route,
        stages=stages,
        prod_section=prod,
        source_sku=product.sku,
        product_id=product.id,
        quantity=Decimal(300),
        status=PlanPositionStatus.released,
    )

    rows = await _rows_by_id(client)
    assert rows[first.id]["free_stock_quantity"] == 1000.0
    assert rows[first.id]["available_remainder_quantity"] == 700.0
    assert rows[second.id]["free_stock_quantity"] == 1000.0
    assert rows[second.id]["available_remainder_quantity"] == 800.0


@pytest.mark.parametrize(
    ("quantity", "expected_deficit"),
    [("1512", 12.0), ("1500", 0.0), ("1200", 0.0)],
)
async def test_deficit_is_shortage_up_to_the_planned_quantity(
    client, session: AsyncSession, quantity: str, expected_deficit: float
) -> None:
    """Дефицит = ``max(0, quantity − available)`` на границе.

    Каждый случай — своя позиция: остаток 1500, позиция released с открытым
    заданием, весь спрос её собственный, поэтому доступно 1500.
    1512 → дефицит 12 (приёмочный случай задачи); 1500 и 1200 → 0: нехватки
    нет и лишний остаток дефицитом не становится.
    """
    product = await _make_product(session, sku="IND-DEF")
    stock, prod, route, stages = await _make_route(session, prefix="IND-DEF")
    plan = await _make_plan(session, prefix="IND-DEF")
    await _seed_good_balance(session, location_id=stock.id, product_id=product.id, qty=1500)

    position = await _add_position(
        session,
        plan=plan,
        route=route,
        stages=stages,
        prod_section=prod,
        source_sku=product.sku,
        product_id=product.id,
        quantity=Decimal(quantity),
        status=PlanPositionStatus.released,
    )

    row = (await _rows_by_id(client))[position.id]
    assert row["available_remainder_quantity"] == 1500.0
    assert row["deficit_quantity"] == expected_deficit


async def test_missing_availability_is_null_and_real_zero_is_zero(
    client, session: AsyncSession
) -> None:
    """«Нет данных» — ``None``, «действительно ноль» — ``0.0``.

    Позиция-пара, компоненты которой не резолвятся: артикулов позиции нет,
    данных о наличии тоже — все три поля ``None``, индикатор не
    показывается. Позиция с маршрутом, у артикула которой нет ни одного
    остатка: данные разрешаются и равны нулю, поэтому ``0.0`` и дефицит в
    плановом количестве позиции.
    """
    product = await _make_product(session, sku="IND-NULL")
    _stock, prod, route, stages = await _make_route(session, prefix="IND-NULL")
    plan = await _make_plan(session, prefix="IND-NULL")

    ghost_pair = await _add_position(
        session,
        plan=plan,
        route=route,
        stages=stages,
        prod_section=prod,
        source_sku="IND-GHOST-A+IND-GHOST-B",
        product_id=None,
        quantity=Decimal(100),
        source_payload={
            "paired_profile": True,
            "components": [{"sku": "IND-GHOST-A"}, {"sku": "IND-GHOST-B"}],
        },
        line_product_id=product.id,
    )
    zero_stock = await _add_position(
        session,
        plan=plan,
        route=route,
        stages=stages,
        prod_section=prod,
        source_sku=product.sku,
        product_id=product.id,
        quantity=Decimal(100),
    )

    rows = await _rows_by_id(client)
    no_data = rows[ghost_pair.id]
    assert no_data["free_stock_quantity"] is None
    assert no_data["available_remainder_quantity"] is None
    assert no_data["deficit_quantity"] is None

    real_zero = rows[zero_stock.id]
    assert real_zero["free_stock_quantity"] == 0.0
    assert real_zero["available_remainder_quantity"] == 0.0
    assert real_zero["deficit_quantity"] == 100.0


async def test_row_list_and_position_card_agree_on_indicator_numbers(
    client, session: AsyncSession
) -> None:
    """Список строк и карточка позиции отдают одни и те же три числа.

    Это два экрана «Контроля выполнения»: список считает индикатор сразу
    для страницы позиций, карточка — для одной позиции. Значения обязаны
    совпадать при непустом спросе, иначе одно и то же число показывается
    по-разному.
    """
    product = await _make_product(session, sku="IND-AGREE")
    stock, prod, route, stages = await _make_route(session, prefix="IND-AGREE")
    plan = await _make_plan(session, prefix="IND-AGREE")
    await _seed_good_balance(session, location_id=stock.id, product_id=product.id, qty=1500)

    approved = await _add_position(
        session,
        plan=plan,
        route=route,
        stages=stages,
        prod_section=prod,
        source_sku=product.sku,
        product_id=product.id,
        quantity=Decimal(200),
    )
    released = await _add_position(
        session,
        plan=plan,
        route=route,
        stages=stages,
        prod_section=prod,
        source_sku=product.sku,
        product_id=product.id,
        quantity=Decimal(300),
        status=PlanPositionStatus.released,
    )

    rows = await _rows_by_id(client)
    assert rows[approved.id]["available_remainder_quantity"] == 1400.0
    assert rows[released.id]["available_remainder_quantity"] == 1500.0

    for position_id in (approved.id, released.id):
        card = await _detail(client, position_id)
        for field in ("free_stock_quantity", "available_remainder_quantity", "deficit_quantity"):
            assert card[field] == rows[position_id][field]
