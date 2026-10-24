"""Журнал и входящие передачи — фиксированное число SQL (#295, пункт 2).

`Section.users/operations/spg_links` и `RouteStage.operations` объявлены
`lazy="selectin"`. Алиасы этих сущностей в выборках журнала и входящих
передач заставляли ORM догружать каждую связь отдельным SELECT'ом: вызов
стоил ~8 лишних запросов, и число не зависело от того, что реально
читается в ответе.

Проверка ловит именно связи Section и операции этапов, а не «число
запросов вообще»: счётчик базовых запросов может меняться по другим
причинам, а эти связи не нужны журналу и входящим вовсе. Отдельно
фиксируется, что число SQL не растёт с числом строк.
"""

from __future__ import annotations

from datetime import UTC, date, datetime, timedelta
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
from app.models.route import ProductionRoute, RouteOperation, RouteStage
from app.models.section import Section
from app.models.transfer import Transfer, TransferStatus
from app.models.work_task import WorkTask, WorkTaskStatus
from app.transfers.queries import (
    get_section_incoming_transfers,
    get_section_transfer_history,
)
from sqlalchemy import delete

from tests.helpers.sql_counter import SqlRecorder

pytestmark = pytest.mark.asyncio

# Таблицы, чтение которых означает, что ORM-сущность поехала по связям.
RELATIONSHIP_TABLES = ("section_operations", "spg_sections", "user_sections")


async def _seed_transfers(session, *, rows: int) -> dict:
    """Две секции, маршрут из двух этапов и ``rows`` открытых передач.

    Передачи пишутся напрямую, без операций склада: здесь важен SQL-профиль
    чтения журнала и входящих, а инварианты ledger проверяются в тестах
    transfer/stock.
    """
    from_section = Section(code="H295-FROM", name="H295 Откуда", type="production", sort_order=0)
    to_section = Section(code="H295-TO", name="H295 Куда", type="production", sort_order=1)
    product = Product(sku="H295-SKU", name="H295", type=ProductType.finished_good, unit="pcs")
    route = ProductionRoute(name="H295-R", is_active=True)
    session.add_all([from_section, to_section, product, route])
    await session.flush()

    from_stage = RouteStage(
        route_id=route.id, sequence=1, section_id=from_section.id, is_final=False,
    )
    to_stage = RouteStage(
        route_id=route.id, sequence=2, section_id=to_section.id, is_final=True,
    )
    session.add_all([from_stage, to_stage])
    await session.flush()
    session.add_all([
        # Порядок операций задан sequence намеренно не по алфавиту: ответ
        # обязан сохранить порядок маршрута, а не порядок вставки/сортировки.
        RouteOperation(
            route_stage_id=from_stage.id, sequence=2,
            operation_code="CUT2", operation_name="Резка вторая",
        ),
        RouteOperation(
            route_stage_id=from_stage.id, sequence=1,
            operation_code="CUT1", operation_name="Резка первая",
        ),
        RouteOperation(
            route_stage_id=to_stage.id, sequence=1,
            operation_code="PACK", operation_name="Упаковка",
        ),
    ])

    plan = ProductionPlan(
        plan_no="H295-P", name="p", status=ProductionPlanStatus.approved,
        period_start=date(2026, 6, 1), period_end=date(2026, 6, 30),
    )
    session.add(plan)
    await session.flush()
    internal = InternalPlan(production_plan_id=plan.id, status=InternalPlanStatus.active)
    session.add(internal)
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
        section_id=from_section.id,
        route_stage_id=from_stage.id,
        product_id=product.id,
        route_id=route.id,
        sequence=1,
        planned_quantity=Decimal(10),
    )
    session.add(line)
    await session.flush()
    from_task = WorkTask(
        section_plan_line_id=line.id,
        section_id=from_section.id,
        product_id=product.id,
        route_stage_id=from_stage.id,
        planned_quantity=Decimal(10),
        status=WorkTaskStatus.in_progress,
    )
    to_task = WorkTask(
        section_plan_line_id=line.id,
        section_id=to_section.id,
        product_id=product.id,
        route_stage_id=to_stage.id,
        planned_quantity=Decimal(10),
        status=WorkTaskStatus.ready,
    )
    session.add_all([from_task, to_task])
    await session.flush()

    base_time = datetime(2026, 6, 15, 12, 0, tzinfo=UTC)
    transfers = [
        Transfer(
            transfer_no=f"H295-{index:03d}",
            from_task_id=from_task.id,
            to_task_id=to_task.id,
            from_section_id=from_section.id,
            to_section_id=to_section.id,
            product_id=product.id,
            sent_quantity=Decimal(1),
            accepted_quantity=Decimal(0),
            status=TransferStatus.sent,
            sent_at=base_time - timedelta(minutes=index),
            created_at=base_time - timedelta(minutes=index),
        )
        for index in range(rows)
    ]
    session.add_all(transfers)
    await session.flush()
    transfer_ids = [transfer.id for transfer in transfers]
    await session.commit()

    result = {
        "from_section_id": from_section.id,
        "to_section_id": to_section.id,
        "to_stage_id": to_stage.id,
        "transfer_ids": transfer_ids,
        "rows": rows,
    }
    # Как в guard'е сводки (#295, п. 1): rollback истекает identity map,
    # иначе ORM отдала бы уже загруженные объекты без SQL и замер врал бы.
    await session.rollback()
    return result


@pytest.mark.parametrize("rows", [2, 6])
async def test_history_query_count_does_not_grow_with_rows(engine, session, rows: int) -> None:
    """Журнал: count + одна выборка с именами операций, всегда 2."""
    fixture = await _seed_transfers(session, rows=rows)

    with SqlRecorder(engine) as recorder:
        body = await get_section_transfer_history(session, section_id=fixture["to_section_id"])

    assert len(body["transfers"]) == rows
    # Порядок журнала прежний: created_at desc (новые сверху).
    assert [item["transfer_id"] for item in body["transfers"]] == fixture["transfer_ids"]
    assert recorder.touching(RELATIONSHIP_TABLES) == [], (
        "журнал тянет связи Section: "
        f"{[s[:120] for s in recorder.touching(RELATIONSHIP_TABLES)]}"
    )
    assert len(recorder.queries) == 2, [s[:120] for s in recorder.queries]
    # Ответ не изменился: операции этапов пришли в порядке sequence.
    item = body["transfers"][0]
    assert item["from_operation_name"] == "Резка первая, Резка вторая"
    assert item["to_operation_name"] == "Упаковка"


async def test_stage_without_operations_reads_as_empty_name(engine, session) -> None:
    """Этап без операций — пустая строка, а не NULL и не лишний запрос.

    Имена собираются LEFT JOIN'ом агрегата: у этапа без строк
    ``route_operations`` результата нет, и ответ обязан остаться прежним.
    """
    fixture = await _seed_transfers(session, rows=1)
    await session.execute(
        delete(RouteOperation).where(RouteOperation.route_stage_id == fixture["to_stage_id"])
    )
    await session.commit()

    with SqlRecorder(engine) as recorder:
        history = await get_section_transfer_history(
            session, section_id=fixture["to_section_id"]
        )
        incoming = await get_section_incoming_transfers(
            session, section_id=fixture["to_section_id"]
        )

    assert history["transfers"][0]["to_operation_name"] == ""
    assert incoming["incoming_transfers"][0]["to_operation_name"] == ""
    assert len(recorder.queries) == 3, [s[:120] for s in recorder.queries]


@pytest.mark.parametrize("rows", [2, 6])
async def test_incoming_query_count_does_not_grow_with_rows(engine, session, rows: int) -> None:
    """Входящие: одна выборка с именами операций, без selectin вовсе."""
    fixture = await _seed_transfers(session, rows=rows)

    with SqlRecorder(engine) as recorder:
        body = await get_section_incoming_transfers(session, section_id=fixture["to_section_id"])

    assert len(body["incoming_transfers"]) == rows
    # Порядок входящих прежний: sent_at desc, затем id desc.
    assert [
        item["transfer_id"] for item in body["incoming_transfers"]
    ] == fixture["transfer_ids"]
    assert recorder.touching(RELATIONSHIP_TABLES) == [], (
        "входящие тянут связи Section: "
        f"{[s[:120] for s in recorder.touching(RELATIONSHIP_TABLES)]}"
    )
    assert len(recorder.queries) == 1, [s[:120] for s in recorder.queries]
    # Формат ответа сохранён, имена операций — в порядке маршрута.
    item = body["incoming_transfers"][0]
    assert item["from_operation_name"] == "Резка первая, Резка вторая"
    assert item["to_operation_name"] == "Упаковка"
    assert item["from_section_code"] == "H295-FROM"
    assert item["to_section_code"] == "H295-TO"
    assert item["product_sku"] == "H295-SKU"
    assert item["remaining_quantity"] == "1"
