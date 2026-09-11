"""Детальная статистика по парному артикулу и свободный остаток пары.

Парная строка плана — составной ``A+B`` (ADR-0023): склад ведёт сырьё
поштучно, поэтому ``product-wip-stats`` раскрывает остатки покомпонентно,
задачи «в работе» собирает по позициям пары (а не по продукту), а индикатор
свободного остатка пары — минимум по компонентам (нужны равные количества).
"""
from __future__ import annotations

from datetime import UTC, date, datetime
from decimal import Decimal

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.internal_plan import InternalPlan, SectionPlanLine
from app.models.product import Product, ProductPair, ProductType
from app.models.production_plan import (
    PlanPosition,
    PlanPositionRouteOrigin,
    PlanPositionStatus,
    PlanPositionValidationStatus,
    PlanSourceType,
    ProductionPlan,
    ProductionPlanStatus,
)
from app.models.route import ProductionRoute, RouteOperation, RouteStage
from app.models.section import Section
from app.models.work_task import WorkTask, WorkTaskStatus
from app.stock import Reason, StockCommand, StockCommandService

pytestmark = pytest.mark.asyncio


async def _make_pair_products(
    session: AsyncSession, *, sku_a: str, sku_b: str, with_pair: bool
) -> tuple[Product, Product]:
    """Два сырьевых артикула; ``with_pair`` — строка в справочнике пар.

    Порядок канонический: ``product_a`` — артикул с меньшим id (вставлен первым).
    """
    product_a = Product(sku=sku_a, name=f"Raw {sku_a}", type=ProductType.component, unit="pcs")
    product_b = Product(sku=sku_b, name=f"Raw {sku_b}", type=ProductType.component, unit="pcs")
    session.add_all([product_a, product_b])
    await session.flush()
    if with_pair:
        session.add(
            ProductPair(
                product_a_id=min(product_a.id, product_b.id),
                product_b_id=max(product_a.id, product_b.id),
                quantity_per_hanger={},
            )
        )
        await session.flush()
    assert product_a.id < product_b.id
    return product_a, product_b


async def _make_route(
    session: AsyncSession, *, prefix: str
) -> tuple[Section, Section, ProductionRoute, list[RouteStage]]:
    """Маршрут склад → производство: секции, этапы и операции."""
    stock = Section(code=f"{prefix}-STK", name="Склад", type="raw_stock", is_active=True, sort_order=0)
    prod = Section(code=f"{prefix}-PROD", name="Участок", type="production", is_active=True, sort_order=1)
    session.add_all([stock, prod])
    await session.flush()

    route = ProductionRoute(name=f"Route {prefix}", is_active=True)
    session.add(route)
    await session.flush()

    stages: list[RouteStage] = []
    for idx, (section, op_code) in enumerate([(stock, "ISSUE"), (prod, "DRILL")], start=1):
        stage = RouteStage(route_id=route.id, sequence=idx, section_id=section.id, is_final=idx == 2)
        session.add(stage)
        await session.flush()
        session.add(
            RouteOperation(route_stage_id=stage.id, sequence=1, operation_code=op_code, operation_name=op_code)
        )
        stages.append(stage)
    await session.flush()
    return stock, prod, route, stages


async def _make_plan(session: AsyncSession, *, prefix: str) -> ProductionPlan:
    plan = ProductionPlan(
        plan_no=f"PLAN-{prefix}",
        name=f"Plan {prefix}",
        status=ProductionPlanStatus.approved,
        period_start=date(2026, 6, 1),
        period_end=date(2026, 6, 30),
    )
    session.add(plan)
    await session.flush()
    return plan


async def _seed_good_balance(
    session: AsyncSession, *, location_id: int, product_id: int, qty: int
) -> None:
    """Физический GOOD-остаток артикула на складе."""
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


async def _add_position_with_task(
    session: AsyncSession,
    *,
    plan: ProductionPlan,
    route: ProductionRoute,
    stages: list[RouteStage],
    prod_section: Section,
    source_sku: str,
    position_product_id: int | None,
    effective_product_id: int,
    source_payload: dict | None = None,
    dimensions: dict | None = None,
    task_status: WorkTaskStatus = WorkTaskStatus.ready,
    with_task: bool = True,
    status: PlanPositionStatus = PlanPositionStatus.approved,
    quantity: Decimal = Decimal("100"),
) -> PlanPosition:
    """Позиция плана и её активная задача.

    ``position_product_id=None`` — парная строка; ``effective_product_id`` —
    продукт, который позиция пишет в строку/задачу (у пары это product_a).
    ``status=released`` + ``with_task`` — позиция запущена в работу и занимает
    свободный остаток своих продуктов.
    """
    position = PlanPosition(
        production_plan_id=plan.id,
        product_id=position_product_id,
        source_type=PlanSourceType.excel_import,
        source_sku=source_sku,
        source_name=source_sku,
        quantity=quantity,
        source_payload=source_payload or {},
        status=status,
        validation_status=PlanPositionValidationStatus.valid,
        validation_errors=[],
        route_id=route.id,
        route_origin=PlanPositionRouteOrigin.manual_confirmed,
        route_assigned_at=datetime.now(UTC),
        route_manual_confirmed_at=datetime.now(UTC),
    )
    session.add(position)
    await session.flush()

    internal = InternalPlan(production_plan_id=plan.id)
    session.add(internal)
    await session.flush()

    line = SectionPlanLine(
        internal_plan_id=internal.id,
        plan_position_id=position.id,
        section_id=prod_section.id,
        product_id=effective_product_id,
        route_id=route.id,
        route_stage_id=stages[1].id,
        sequence=1,
        planned_quantity=quantity,
    )
    session.add(line)
    await session.flush()

    if with_task:
        session.add(
            WorkTask(
                section_plan_line_id=line.id,
                section_id=prod_section.id,
                product_id=effective_product_id,
                route_stage_id=stages[1].id,
                planned_quantity=quantity,
                dimensions=dimensions,
                status=task_status,
            )
        )
    await session.commit()
    return position


def _pair_payload(sku_a: str, sku_b: str, *, order: str = "ab") -> dict:
    skus = [sku_a, sku_b] if order == "ab" else [sku_b, sku_a]
    return {"paired_profile": True, "components": [{"sku": sku} for sku in skus]}


async def test_wip_stats_pair_components_have_own_remainders(client, session: AsyncSession) -> None:
    """Остатки пары раскрываются по компонентам: у каждого — свой StockBalance.

    Склад ведётся поштучно, поэтому верхнеуровневые ``remainders`` пусты,
    ``product_id`` пары не существует, а порядок компонентов канонический
    (product_a, product_b) независимо от порядка в запрошенном артикуле.
    """
    product_a, product_b = await _make_pair_products(
        session, sku_a="WPSP-A", sku_b="WPSP-B", with_pair=True
    )
    stock, _prod, _route, _stages = await _make_route(session, prefix="WPSP")
    await _seed_good_balance(session, location_id=stock.id, product_id=product_a.id, qty=5)
    await _seed_good_balance(session, location_id=stock.id, product_id=product_b.id, qty=2)

    resp = await client.get("/api/production-planning/product-wip-stats/WPSP-A+WPSP-B")
    assert resp.status_code == 200, resp.text
    data = resp.json()

    assert data["is_pair"] is True
    assert data["warning"] is None
    assert data["product_id"] is None
    assert data["remainders"] == []
    assert data["product_name"] == "Raw WPSP-A + Raw WPSP-B"
    assert [component["sku"] for component in data["components"]] == ["WPSP-A", "WPSP-B"]

    component_a, component_b = data["components"]
    assert component_a["product_id"] == product_a.id
    assert component_b["product_id"] == product_b.id
    assert [row["quantity"] for row in component_a["remainders"]] == [5.0]
    assert [row["quantity"] for row in component_b["remainders"]] == [2.0]

    # Резолв пары неупорядоченный: обратный порядок в артикуле — тот же расклад.
    reversed_resp = await client.get("/api/production-planning/product-wip-stats/WPSP-B+WPSP-A")
    assert reversed_resp.status_code == 200, reversed_resp.text
    reversed_data = reversed_resp.json()
    assert [component["sku"] for component in reversed_data["components"]] == ["WPSP-A", "WPSP-B"]
    assert [row["quantity"] for row in reversed_data["components"][0]["remainders"]] == [5.0]
    assert [row["quantity"] for row in reversed_data["components"][1]["remainders"]] == [2.0]


async def test_wip_stats_pair_in_work_only_pair_positions(client, session: AsyncSession) -> None:
    """«В работе» пары — задачи только её позиций, задачи одиночной позиции того же артикула не подмешиваются.

    Парная задача и позиция с обратным порядком компонентов (``B+A``)
    попадают в сводку; задача одиночной позиции артикула A — нет, хотя
    ``WorkTask.product_id`` у всех трёх равен product_a.
    """
    product_a, product_b = await _make_pair_products(
        session, sku_a="WPSW-A", sku_b="WPSW-B", with_pair=True
    )
    _stock, prod, route, stages = await _make_route(session, prefix="WPSW")
    plan = await _make_plan(session, prefix="WPSW")

    await _add_position_with_task(
        session,
        plan=plan, route=route, stages=stages, prod_section=prod,
        source_sku="WPSW-A+WPSW-B",
        position_product_id=None,
        effective_product_id=product_a.id,
        source_payload=_pair_payload("WPSW-A", "WPSW-B"),
        dimensions={"length_mm": 1000},
        task_status=WorkTaskStatus.in_progress,
    )
    # Одиночная позиция того же артикула A: её задача в сводку пары не входит.
    await _add_position_with_task(
        session,
        plan=plan, route=route, stages=stages, prod_section=prod,
        source_sku="WPSW-A",
        position_product_id=product_a.id,
        effective_product_id=product_a.id,
        dimensions={"length_mm": 2000},
        task_status=WorkTaskStatus.ready,
    )
    # Позиции пишут компоненты в порядке строки Excel — обратный порядок тоже пара.
    await _add_position_with_task(
        session,
        plan=plan, route=route, stages=stages, prod_section=prod,
        source_sku="WPSW-B+WPSW-A",
        position_product_id=None,
        effective_product_id=product_a.id,
        source_payload=_pair_payload("WPSW-A", "WPSW-B", order="ba"),
        dimensions={"length_mm": 3000},
        task_status=WorkTaskStatus.in_progress,
    )

    resp = await client.get("/api/production-planning/product-wip-stats/WPSW-A+WPSW-B")
    assert resp.status_code == 200, resp.text
    data = resp.json()

    assert data["is_pair"] is True
    assert sorted(task["dimensions"]["length_mm"] for task in data["in_work"]) == [1000, 3000]
    assert all(task["active_tasks_count"] == 1 for task in data["in_work"])


async def test_wip_stats_pair_without_pair_row_degrades(client, session: AsyncSession) -> None:
    """Составной SKU без строки в product_pairs: 200, warning, компоненты по SKU."""
    product_a, product_b = await _make_pair_products(
        session, sku_a="WPSD-A", sku_b="WPSD-B", with_pair=False
    )

    resp = await client.get("/api/production-planning/product-wip-stats/WPSD-A+WPSD-B")
    assert resp.status_code == 200, resp.text
    data = resp.json()

    assert data["is_pair"] is True
    assert data["warning"] == "product_pair_not_found"
    assert data["product_id"] is None
    assert data["product_name"] == "Raw WPSD-A + Raw WPSD-B"
    assert [component["sku"] for component in data["components"]] == ["WPSD-A", "WPSD-B"]
    assert [component["product_id"] for component in data["components"]] == [
        product_a.id,
        product_b.id,
    ]


async def test_wip_stats_pair_partially_missing_component_degrades(client, session: AsyncSession) -> None:
    """Найден только один компонент: 200 + warning, отсутствующий раскрыт без остатков."""
    product_a = Product(sku="WPSD-ONLY", name="Raw WPSD-ONLY", type=ProductType.component, unit="pcs")
    session.add(product_a)
    await session.flush()

    resp = await client.get("/api/production-planning/product-wip-stats/WPSD-ONLY+WPSD-GHOST")
    assert resp.status_code == 200, resp.text
    data = resp.json()

    assert data["warning"] == "product_pair_not_found"
    component_a, ghost = data["components"]
    assert component_a["product_id"] == product_a.id
    assert component_a["sku"] == "WPSD-ONLY"
    assert ghost["product_id"] is None
    assert ghost["remainders"] == []


async def test_wip_stats_pair_no_component_found_404(client, session: AsyncSession) -> None:
    """Ни один компонент не существует как Product — 404, а не пустая сводка."""
    resp = await client.get(
        "/api/production-planning/product-wip-stats/WPSD-GHOST-A+WPSD-GHOST-B"
    )

    assert resp.status_code == 404
    assert resp.json()["detail"] == "Product not found"


async def test_wip_stats_pair_rows_available_remainder_is_min_of_components(
    client, session: AsyncSession
) -> None:
    """Индикатор пары = минимум свободного остатка компонентов, а не product_a.

    A=5, B=2 → пара показывает 2 (запуск требует равных количеств обоих);
    одиночная позиция того же артикула A по-прежнему показывает свой остаток 5.
    Значение одинаково в списке строк и в карточке позиции.
    """
    product_a, product_b = await _make_pair_products(
        session, sku_a="WPSR-A", sku_b="WPSR-B", with_pair=True
    )
    stock, prod, route, stages = await _make_route(session, prefix="WPSR")
    await _seed_good_balance(session, location_id=stock.id, product_id=product_a.id, qty=5)
    await _seed_good_balance(session, location_id=stock.id, product_id=product_b.id, qty=2)
    plan = await _make_plan(session, prefix="WPSR")

    pair_position = await _add_position_with_task(
        session,
        plan=plan, route=route, stages=stages, prod_section=prod,
        source_sku="WPSR-A+WPSR-B",
        position_product_id=None,
        effective_product_id=product_a.id,
        source_payload=_pair_payload("WPSR-A", "WPSR-B"),
        with_task=False,
    )
    single_position = await _add_position_with_task(
        session,
        plan=plan, route=route, stages=stages, prod_section=prod,
        source_sku="WPSR-A",
        position_product_id=product_a.id,
        effective_product_id=product_a.id,
        with_task=False,
    )

    rows_resp = await client.get("/api/production-planning/rows?limit=500")
    assert rows_resp.status_code == 200, rows_resp.text
    rows_by_id = {row["plan_position_id"]: row for row in rows_resp.json()["rows"]}
    assert rows_by_id[pair_position.id]["available_remainder_quantity"] == 2.0
    assert rows_by_id[single_position.id]["available_remainder_quantity"] == 5.0

    pair_detail = await client.get(f"/api/production-planning/rows/{pair_position.id}")
    assert pair_detail.status_code == 200, pair_detail.text
    assert pair_detail.json()["available_remainder_quantity"] == 2.0

    single_detail = await client.get(f"/api/production-planning/rows/{single_position.id}")
    assert single_detail.status_code == 200, single_detail.text
    assert single_detail.json()["available_remainder_quantity"] == 5.0


async def test_available_remainder_pair_launch_reduces_both_components(
    client, session: AsyncSession
) -> None:
    """Запуск пары вычитает её количество у ОБОИХ компонентов, а не только у product_a.

    A=100, B=10; парная позиция released, quantity=5, задача не завершена.
    Свободный остаток пары = ``min(100−5, 10−5) = 5``. До фикса строки и задачи
    пары несут только product_a, поэтому из B вычитался 0 и индикатор показывал
    ``min(95, 10) = 10``.

    Одиночная released-позиция B=2 делит с парой общий свободный остаток B:
    показатель = ``10−5−2 = 3`` — парная и собственная заявки учтены по одному
    разу, повторного парного вычета нет.
    """
    product_a, product_b = await _make_pair_products(
        session, sku_a="WPSL-A", sku_b="WPSL-B", with_pair=True
    )
    stock, prod, route, stages = await _make_route(session, prefix="WPSL")
    await _seed_good_balance(session, location_id=stock.id, product_id=product_a.id, qty=100)
    await _seed_good_balance(session, location_id=stock.id, product_id=product_b.id, qty=10)
    plan = await _make_plan(session, prefix="WPSL")

    pair_position = await _add_position_with_task(
        session,
        plan=plan, route=route, stages=stages, prod_section=prod,
        source_sku="WPSL-A+WPSL-B",
        position_product_id=None,
        effective_product_id=product_a.id,
        source_payload=_pair_payload("WPSL-A", "WPSL-B"),
        status=PlanPositionStatus.released,
        quantity=Decimal("5"),
    )

    rows_resp = await client.get("/api/production-planning/rows?limit=500")
    assert rows_resp.status_code == 200, rows_resp.text
    rows_by_id = {row["plan_position_id"]: row for row in rows_resp.json()["rows"]}
    assert rows_by_id[pair_position.id]["available_remainder_quantity"] == 5.0

    pair_detail = await client.get(f"/api/production-planning/rows/{pair_position.id}")
    assert pair_detail.status_code == 200, pair_detail.text
    assert pair_detail.json()["available_remainder_quantity"] == 5.0

    single_position = await _add_position_with_task(
        session,
        plan=plan, route=route, stages=stages, prod_section=prod,
        source_sku="WPSL-B",
        position_product_id=product_b.id,
        effective_product_id=product_b.id,
        status=PlanPositionStatus.released,
        quantity=Decimal("2"),
    )

    rows_after = await client.get("/api/production-planning/rows?limit=500")
    assert rows_after.status_code == 200, rows_after.text
    after_by_id = {row["plan_position_id"]: row for row in rows_after.json()["rows"]}
    assert after_by_id[single_position.id]["available_remainder_quantity"] == 3.0
    assert after_by_id[pair_position.id]["available_remainder_quantity"] == 3.0


async def test_wip_stats_pair_header_keeps_missing_component_sku(
    client, session: AsyncSession
) -> None:
    """Заголовок парной сводки несёт оба компонента, ненайденный — своим SKU.

    Пара не создана в ``product_pairs`` (``warning="product_pair_not_found"``),
    второй компонент отсутствует в ``products``: до фикса заголовок собирался
    только из найденных продуктов и терял ``GHOST``, показывая один ``A``.
    """
    session.add(Product(sku="WPSH-REAL", name="Raw WPSH-REAL", type=ProductType.component, unit="pcs"))
    await session.flush()

    resp = await client.get("/api/production-planning/product-wip-stats/WPSH-REAL+WPSH-GHOST")
    assert resp.status_code == 200, resp.text
    data = resp.json()

    assert data["warning"] == "product_pair_not_found"
    assert data["product_name"] == "Raw WPSH-REAL + WPSH-GHOST"
    assert [component["sku"] for component in data["components"]] == ["WPSH-REAL", "WPSH-GHOST"]
    assert data["components"][1]["product_id"] is None


async def test_available_remainder_unresolvable_pair_still_consumes_line_product(
    client, session: AsyncSession
) -> None:
    """Запуск нерезолвящейся пары списывает quantity с продукта её строки.

    Пара без снапшота и без строки в ``product_pairs`` не раскрывается по
    компонентам, но её строки несут product_a: A=100, B=100, пара released,
    quantity=5, задача не завершена → у A свободно ``100−5 = 95``, у B — 100
    (на второй компонент заявка нерезолвящейся пары не распространяется).
    Одиночная released-позиция A=2 даёт ``95−2 = 93``; без списания запуска
    пары было бы 98 — то есть остаток A завышался у всех позиций артикула.
    """
    product_a, product_b = await _make_pair_products(
        session, sku_a="WPSU-A", sku_b="WPSU-B", with_pair=False
    )
    stock, prod, route, stages = await _make_route(session, prefix="WPSU")
    await _seed_good_balance(session, location_id=stock.id, product_id=product_a.id, qty=100)
    await _seed_good_balance(session, location_id=stock.id, product_id=product_b.id, qty=100)
    plan = await _make_plan(session, prefix="WPSU")

    await _add_position_with_task(
        session,
        plan=plan, route=route, stages=stages, prod_section=prod,
        source_sku="WPSU-A+WPSU-B",
        position_product_id=None,
        effective_product_id=product_a.id,
        status=PlanPositionStatus.released,
        quantity=Decimal("5"),
    )
    single_a = await _add_position_with_task(
        session,
        plan=plan, route=route, stages=stages, prod_section=prod,
        source_sku="WPSU-A",
        position_product_id=product_a.id,
        effective_product_id=product_a.id,
        status=PlanPositionStatus.released,
        quantity=Decimal("2"),
    )
    # Не запущена: только читает свободный остаток B.
    single_b = await _add_position_with_task(
        session,
        plan=plan, route=route, stages=stages, prod_section=prod,
        source_sku="WPSU-B",
        position_product_id=product_b.id,
        effective_product_id=product_b.id,
        with_task=False,
    )

    rows_resp = await client.get("/api/production-planning/rows?limit=500")
    assert rows_resp.status_code == 200, rows_resp.text
    rows_by_id = {row["plan_position_id"]: row for row in rows_resp.json()["rows"]}
    assert rows_by_id[single_a.id]["available_remainder_quantity"] == 93.0
    assert rows_by_id[single_b.id]["available_remainder_quantity"] == 100.0
