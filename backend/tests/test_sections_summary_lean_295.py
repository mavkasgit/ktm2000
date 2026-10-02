"""Сводка участков не тянет связи Section (#295, пункт 1).

`Section.users/operations/spg_links` объявлены `lazy="selectin"`, поэтому
любое чтение `Section` — а сводка читает его на каждом 12-секундном тике —
тащит три лишних SELECT'а. Проверка ловит именно их, а не «число запросов
вообще»: счётчик агрегатов может меняться по другим причинам, а связи Section
в сводке не нужны вовсе.
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal

import pytest
from app.models.internal_plan import InternalPlan, InternalPlanStatus, SectionPlanLine
from app.models.product import Product, ProductType
from app.models.production_plan import (
    PlanPosition,
    PlanPositionStatus,
    PlanPositionValidationStatus,
    PlanSourceType,
    ProductionPlan,
    ProductionPlanStatus,
)
from app.models.route import ProductionRoute, RouteStage, SectionOperation
from app.models.section import Section
from app.models.work_task import WorkTask, WorkTaskStatus
from app.services.shopfloor.queries_sections import get_sections_summary
from sqlalchemy import event

pytestmark = pytest.mark.asyncio

# Таблицы, чтение которых означает, что ORM-сущность Section поехала по связям.
RELATIONSHIP_TABLES = ("section_operations", "spg_sections", "user_sections")


class SqlRecorder:
    def __init__(self, engine) -> None:
        self.engine = engine
        self.statements: list[str] = []

    def __enter__(self) -> SqlRecorder:
        event.listen(self.engine.sync_engine, "before_cursor_execute", self._on_execute)
        return self

    def __exit__(self, *exc) -> None:
        event.remove(self.engine.sync_engine, "before_cursor_execute", self._on_execute)

    def _on_execute(self, conn, cursor, statement, parameters, context, executemany) -> None:
        self.statements.append(" ".join(statement.split()))

    def touching(self, tables: tuple[str, ...]) -> list[str]:
        return [s for s in self.statements if any(f"FROM {table}" in s for table in tables)]


async def _seed_sections(session, count: int) -> None:
    """count секций; у каждой своя операция — иначе батч связей не отработал бы."""
    product = Product(sku="S295-SKU", name="SKU", type=ProductType.finished_good, unit="pcs")
    session.add(product)
    await session.flush()

    plan = ProductionPlan(
        plan_no="S295-P", name="p", status=ProductionPlanStatus.approved,
        period_start=date(2026, 6, 1), period_end=date(2026, 6, 30),
    )
    session.add(plan)
    await session.flush()

    internal = InternalPlan(production_plan_id=plan.id, status=InternalPlanStatus.active)
    session.add(internal)
    await session.flush()

    for index in range(count):
        section = Section(code=f"S295-{index}", name=f"Участок {index}", type="production", sort_order=index)
        session.add(section)
        await session.flush()
        session.add(SectionOperation(section_id=section.id, operation_code=f"OP{index}", operation_name=f"Оп {index}"))

        route = ProductionRoute(name=f"S295-R{index}", is_active=True)
        session.add(route)
        await session.flush()
        stage = RouteStage(route_id=route.id, sequence=1, section_id=section.id, is_final=True)
        session.add(stage)
        await session.flush()

        position = PlanPosition(
            production_plan_id=plan.id,
            product_id=product.id,
            source_type=PlanSourceType.manual,
            source_sku=product.sku,
            source_name=product.name,
            quantity=Decimal(10),
            source_payload={},
            status=PlanPositionStatus.approved,
            validation_status=PlanPositionValidationStatus.valid,
            validation_errors=[],
            period_start=plan.period_start,
            period_end=plan.period_end,
            has_pack_ops=False,
            route_id=route.id,
        )
        session.add(position)
        await session.flush()
        line = SectionPlanLine(
            internal_plan_id=internal.id,
            plan_position_id=position.id,
            section_id=section.id,
            route_stage_id=stage.id,
            product_id=product.id,
            route_id=route.id,
            sequence=1,
            planned_quantity=Decimal(10),
        )
        session.add(line)
        await session.flush()
        session.add(
            WorkTask(
                section_plan_line_id=line.id,
                section_id=section.id,
                product_id=product.id,
                route_stage_id=stage.id,
                planned_quantity=Decimal(10),
                status=WorkTaskStatus.ready,
            )
        )
    await session.commit()


@pytest.mark.parametrize("sections", [3, 30])
async def test_summary_does_not_load_section_relationships(engine, session, sections: int) -> None:
    """Ни `users`, ни `operations`, ни `spg_links` сводке не нужны (#295)."""
    await _seed_sections(session, sections)
    await session.rollback()

    with SqlRecorder(engine) as recorder:
        await get_sections_summary(session)

    assert recorder.touching(RELATIONSHIP_TABLES) == [], (
        "сводка тянет связи Section: "
        f"{[s[:80] for s in recorder.touching(RELATIONSHIP_TABLES)]}"
    )


@pytest.mark.parametrize("sections", [3, 30])
async def test_summary_query_count_does_not_grow_with_sections(engine, session, sections: int) -> None:
    """Сводка — фиксированное число запросов: агрегаты плюс выборка секций."""
    await _seed_sections(session, sections)
    await session.rollback()

    with SqlRecorder(engine) as recorder:
        summary = await get_sections_summary(session)

    assert len(summary["sections"]) == sections
    # 3 агрегата + выборка секций; лишних запросов на связи быть не должно
    # (это проверяет предыдущий тест), поэтому потолок жёсткий.
    assert len(recorder.statements) <= 5, [s[:80] for s in recorder.statements]


async def test_summary_still_returns_counters(engine, session) -> None:
    """Ответ сводки не изменился: секции со счётчиками и без связей в JSON."""
    await _seed_sections(session, 2)
    await session.rollback()

    summary = await get_sections_summary(session)

    assert len(summary["sections"]) == 2
    first = summary["sections"][0]
    assert first["section_code"] == "S295-0"
    assert first["section_name"] == "Участок 0"
    assert first["total_tasks"] == 1
    assert first["in_progress_count"] == 1
    assert first["completed_count"] == 0
    assert first["waiting_count"] == 0
    assert first["incoming_transfers_count"] == 0
    # Связей в ответе нет и не должно быть: сводка отдаёт плоские счётчики.
    assert "users" not in first and "operations" not in first