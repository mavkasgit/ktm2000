"""Складской этап маршрута — полноценный этап для ``validate_route_match`` (#178).

До #178 складские шаги маршрута материализовались как
``RouteStage(section_id=<склад>)``. После #178 склад стал транзит-хопом:
``stage_kind='transit'``, ``section_id IS NULL``, склад лежит в
``storage_section_id`` (``backend/app/models/route.py:44-113``,
инвариант закреплён триггером ``fn_check_route_stage_transit_invariants``
в ``backend/app/db/triggers.py:31-66``).

``validate_route_match`` собирает множество секций этапов маршрута, чтобы
сравнить его с ``required``/``excluded`` из правил подбора
(``backend/app/services/route_validation.py:120-140``). Если в это множество
попадает только ``section_id``, то ЛЮБОЙ маршрут со складскими этапами
объявляется неполным: правило ``require_section`` на склад даёт
``route_missing_required_step``, а правило ``exclude_section`` на склад
молчит, хотя склад в маршруте есть. Итог — approve позиции упирается в
форс-аппрув по несуществующей причине.

Контракты, которые защищают тесты:

- складской хоп (``storage_section_id``) удовлетворяет ``require_section``
  так же, как обычный цеховой этап;
- склад, которого в маршруте нет, по-прежнему даёт
  ``route_missing_required_step`` (негативный контроль: без него первый
  тест проходит и на неверном коде);
- складской хоп учитывается и в ``exclude_section``, то есть попадает в
  множество секций маршрута, а не выпадает из него.
"""
from __future__ import annotations

from datetime import date
from decimal import Decimal

import pytest
from app.models.product import Product, ProductType
from app.models.production_plan import (
    PlanPosition,
    PlanPositionStatus,
    PlanPositionValidationStatus,
    PlanSourceType,
    ProductionPlan,
)
from app.models.route import ProductionRoute, RouteSelectionRule, RouteStage
from app.models.section import Section
from app.services.route_validation import validate_route_match
from sqlalchemy.ext.asyncio import AsyncSession

# Типы секций-складов: триггер ``fn_check_route_stage_transit_invariants``
# допускает складом только raw_stock/wip_stock/finished_stock/scrap/terminal.
STORAGE_TYPES = {"raw_stock", "wip_stock", "finished_stock", "scrap", "terminal"}

# Маршрут: выдача сырья (склад) → сверло (цех) → промежуточный склад →
# упаковка (цех) → склад ГП. Складские шаги — транзит-хопы.
STAGE_DEFS: list[tuple[str, str]] = [
    ("ISSUE", "raw_stock"),
    ("DRILLING", "production"),
    ("INTER", "wip_stock"),
    ("PACKING", "production"),
    ("FINAL", "finished_stock"),
]


async def _make_transit_route(session: AsyncSession, sku: str) -> tuple[Product, ProductionRoute, dict[str, Section]]:
    """Продукт + маршрут, где складские этапы лежат в ``storage_section_id``."""
    product = Product(sku=sku, name=f"ГП {sku}", type=ProductType.finished_good, unit="pcs")
    session.add(product)
    await session.flush()

    sections: dict[str, Section] = {}
    for logical_code, section_type in STAGE_DEFS:
        section = Section(code=f"{sku}-{logical_code}", name=logical_code, type=section_type, is_active=True)
        session.add(section)
        sections[logical_code] = section
    await session.flush()

    route = ProductionRoute(name=f"Main-{sku}", is_active=True)
    session.add(route)
    await session.flush()

    for sequence, (logical_code, section_type) in enumerate(STAGE_DEFS, start=1):
        section = sections[logical_code]
        if section_type in STORAGE_TYPES:
            # Транзит-хоп #178: цеховой ``section_id`` пуст, склад — в
            # ``storage_section_id``. Нарушение инварианта триггер не даст.
            session.add(
                RouteStage(
                    route_id=route.id,
                    sequence=sequence,
                    stage_kind="transit",
                    section_id=None,
                    storage_section_id=section.id,
                    is_final=sequence == len(STAGE_DEFS),
                )
            )
        else:
            session.add(
                RouteStage(
                    route_id=route.id,
                    sequence=sequence,
                    stage_kind="production",
                    section_id=section.id,
                    storage_section_id=None,
                    is_final=sequence == len(STAGE_DEFS),
                )
            )
        await session.flush()

    return product, route, sections


async def _make_position(session: AsyncSession, product: Product, route: ProductionRoute, sku: str) -> PlanPosition:
    """Позиция плана с назначенным маршрутом (origin не manual — валидация идёт)."""
    plan = ProductionPlan(
        plan_no=f"PLAN-{sku}",
        name=f"План {sku}",
        period_start=date(2026, 5, 1),
        period_end=date(2026, 5, 31),
    )
    session.add(plan)
    await session.flush()

    position = PlanPosition(
        production_plan_id=plan.id,
        product_id=product.id,
        source_type=PlanSourceType.excel_import,
        source_sku=product.sku,
        source_name=product.name,
        quantity=Decimal(100),
        source_payload={
            "operation_code": "DRILL",
            "output_kind": "finished_good",
            "additional_pack_operations": [],
            "paired_profile": False,
        },
        status=PlanPositionStatus.draft,
        validation_status=PlanPositionValidationStatus.pending,
        validation_errors=[],
        route_id=route.id,
    )
    session.add(position)
    await session.flush()
    return position


async def _add_rule(
    session: AsyncSession,
    sku: str,
    action: str,
    logical_codes: list[str],
    sections: dict[str, Section],
) -> None:
    """Глобальное правило подбора ``require_section``/``exclude_section``."""
    session.add(
        RouteSelectionRule(
            code=f"rule-{sku}-{action}-{'-'.join(logical_codes)}",
            name=f"Правило {action} {sku}",
            priority=100,
            is_active=True,
            phase="route_select",
            conditions=[],
            actions=[
                {"action": action, "section_id": sections[code].id}
                for code in logical_codes
            ],
        )
    )
    await session.flush()


async def _add_absent_storage_section(session: AsyncSession, sku: str) -> Section:
    """Склад ГП, которого в маршруте нет — для негативного контроля."""
    section = Section(code=f"{sku}-OTHER_STOCK", name="Другой склад", type="finished_stock", is_active=True)
    session.add(section)
    await session.flush()
    return section


# ─── складской этап как этап маршрута ────────────────────────────────────────


@pytest.mark.asyncio
async def test_transit_storage_hop_satisfies_required_section(session: AsyncSession) -> None:
    """Склад в ``storage_section_id`` закрывает ``require_section`` на этот склад."""
    product, route, sections = await _make_transit_route(session, "FG-TRANSIT-REQ")
    position = await _make_position(session, product, route, "FG-TRANSIT-REQ")
    await _add_rule(
        session, "FG-TRANSIT-REQ", "require_section",
        ["ISSUE", "INTER", "FINAL"], sections,
    )

    issues = await validate_route_match(session, position)

    assert issues == [], f"складские хопы не должны считаться отсутствующими этапами: {issues}"


@pytest.mark.asyncio
async def test_required_storage_section_absent_from_route_is_reported(session: AsyncSession) -> None:
    """Негативный контроль: склад, которого в маршруте нет, даёт missing."""
    product, route, _sections = await _make_transit_route(session, "FG-TRANSIT-NEG")
    position = await _make_position(session, product, route, "FG-TRANSIT-NEG")
    absent = await _add_absent_storage_section(session, "FG-TRANSIT-NEG")
    await _add_rule(session, "FG-TRANSIT-NEG", "require_section", ["OTHER_STOCK"], {"OTHER_STOCK": absent})

    issues = await validate_route_match(session, position)

    assert issues == ["route_missing_required_step: FG-TRANSIT-NEG-OTHER_STOCK"]


@pytest.mark.asyncio
async def test_transit_storage_hop_is_detected_as_excluded_section(session: AsyncSession) -> None:
    """Склад в ``storage_section_id`` попадает в множество этапов и для exclude."""
    product, route, sections = await _make_transit_route(session, "FG-TRANSIT-EXCL")
    position = await _make_position(session, product, route, "FG-TRANSIT-EXCL")
    await _add_rule(session, "FG-TRANSIT-EXCL", "exclude_section", ["FINAL"], sections)

    issues = await validate_route_match(session, position)

    assert issues == ["route_contains_excluded_step: FG-TRANSIT-EXCL-FINAL"]
