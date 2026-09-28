"""Пропуск этапа позиции как закрытый результат (тикет #207, решение Q6).

Защищаемые контракты, каждый — отдельный тест:

* ``skip_stage`` пишет ``skipped`` + причину и НЕ создаёт проводок ledger;
* этап без задания всё равно появляется в прогрессе позиции;
* позиция «выполнено + пропущено» читается как выполненная — и в списке, и
  в карточке;
* уже выполненный и уже отменённый этап пропустить нельзя, и неудачный
  пропуск не меняет состояние;
* пропуск требует причины;
* пропущенный этап не держит позицию открытой для индикатора остатка.
"""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal

import pytest
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.internal_plan import InternalPlan, SectionPlanLine
from app.models.product import Product
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
from app.services.shopfloor.operations_skipped import (
    SKIP_REASON_MATERIAL_READY,
    skip_stage,
)
from app.stock import Reason, StockCommand, StockCommandService
from app.stock.models import StockTransaction
from tests.helpers.completed_operations import (
    build_plan as _make_plan,
    build_product as _make_product,
    build_stock_to_shop_route as _make_route,
)

pytestmark = pytest.mark.asyncio




async def _add_position(
    session: AsyncSession,
    *,
    plan: ProductionPlan,
    route: ProductionRoute,
    sections: list[Section],
    stages: list[RouteStage],
    product: Product,
    quantity: Decimal,
    status: PlanPositionStatus = PlanPositionStatus.approved,
    task_statuses: list[WorkTaskStatus | None],
    extra_tasks: list[tuple[int, WorkTaskStatus]] | None = None,
) -> tuple[PlanPosition, list[SectionPlanLine], list[WorkTask | None]]:
    """Позиция плана с двумя этапами.

    ``task_statuses[i]`` — статус задания i-го этапа; ``None`` — этап без
    задания. ``extra_tasks`` — ``(индекс этапа, статус)`` для дополнительных
    заданий на той же строке: этап с несколькими заданиями закрывается иначе,
    чем этап с одним. Возвращает позицию, её строки маршрута и их задания.
    """
    position = PlanPosition(
        production_plan_id=plan.id,
        product_id=product.id,
        source_type=PlanSourceType.excel_import,
        source_sku=product.sku,
        source_name=product.sku,
        quantity=quantity,
        source_payload={},
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

    lines: list[SectionPlanLine] = []
    tasks: list[WorkTask | None] = []
    for idx, stage in enumerate(stages):
        line = SectionPlanLine(
            internal_plan_id=internal.id,
            plan_position_id=position.id,
            section_id=sections[idx].id,
            product_id=product.id,
            route_id=route.id,
            route_stage_id=stage.id,
            sequence=stage.sequence,
            planned_quantity=quantity,
        )
        session.add(line)
        await session.flush()
        lines.append(line)

        if task_statuses[idx] is None:
            tasks.append(None)
            continue
        task = WorkTask(
            section_plan_line_id=line.id,
            section_id=sections[idx].id,
            product_id=product.id,
            route_stage_id=stage.id,
            planned_quantity=quantity,
            status=task_statuses[idx],
        )
        session.add(task)
        tasks.append(task)
        for extra_index, extra_status in extra_tasks or []:
            if extra_index != idx:
                continue
            session.add(
                WorkTask(
                    section_plan_line_id=line.id,
                    section_id=sections[idx].id,
                    product_id=product.id,
                    route_stage_id=stage.id,
                    planned_quantity=quantity,
                    status=extra_status,
                )
            )
    await session.commit()
    return position, lines, tasks


async def _stored_task(session: AsyncSession, task_id: int) -> WorkTask:
    """Задание из базы, а не из кэша сессии: проверяем сохранённые значения."""
    session.expire_all()
    reloaded = await session.get(WorkTask, task_id)
    assert reloaded is not None
    return reloaded


async def _ledger_size(session: AsyncSession) -> int:
    return int(await session.scalar(select(func.count(StockTransaction.id))) or 0)


async def test_skip_stage_closes_the_task_with_reason_and_writes_no_ledger(
    session: AsyncSession,
) -> None:
    """Пропуск ставит ``skipped`` с причиной и не пишет ни одной проводки.

    Материала по пропущенному этапу нет и никогда не было — проводка была бы
    выдуманной, поэтому ledger остаётся пустым.
    """
    product = await _make_product(session, sku="SKIP-ONE")
    stock, prod, route, stages = await _make_route(session, prefix="SKIP-ONE")
    plan = await _make_plan(session, prefix="SKIP-ONE")
    _position, lines, tasks = await _add_position(
        session,
        plan=plan,
        route=route,
        sections=[stock, prod],
        stages=stages,
        product=product,
        quantity=Decimal("100"),
        task_statuses=[WorkTaskStatus.completed, WorkTaskStatus.ready],
    )

    before = await _ledger_size(session)
    skipped = await skip_stage(session, section_plan_line_id=lines[1].id)
    assert await _ledger_size(session) == before

    skipped_id = skipped.id
    stored = await _stored_task(session, skipped_id)
    assert stored.status == WorkTaskStatus.skipped
    assert stored.skip_reason == SKIP_REASON_MATERIAL_READY
    assert stored.id == tasks[1].id


async def test_skip_stage_creates_the_task_when_the_stage_has_none(
    session: AsyncSession,
) -> None:
    """Этап без задания пропустить можно: задание создаётся и закрывается.

    Пропущенный этап обязан быть виден в прогрессе позиции, а не отсутствовать
    в нём. Причина оператора сохраняется как есть.
    """
    product = await _make_product(session, sku="SKIP-NEW")
    stock, prod, route, stages = await _make_route(session, prefix="SKIP-NEW")
    plan = await _make_plan(session, prefix="SKIP-NEW")
    _position, lines, _tasks = await _add_position(
        session,
        plan=plan,
        route=route,
        sections=[stock, prod],
        stages=stages,
        product=product,
        quantity=Decimal("100"),
        task_statuses=[WorkTaskStatus.completed, None],
    )

    line_id = lines[1].id
    created = await skip_stage(
        session, section_plan_line_id=line_id, reason="Заготовка подана с участка"
    )
    created_id = created.id
    stored = await _stored_task(session, created_id)
    assert stored.section_plan_line_id == line_id
    assert stored.status == WorkTaskStatus.skipped
    assert stored.skip_reason == "Заготовка подана с участка"


async def test_position_with_completed_and_skipped_stages_reads_as_completed(
    client, session: AsyncSession
) -> None:
    """Позиция «выполнено + пропущено» закрыта, а пропуск виден как пропуск.

    Первый этап: два задания, одно выполнено, одно пропущено — этап закрыт
    результатом, поэтому ``task_status == "completed"``. Второй этап: единственное
    задание пропущено, поэтому ``task_status == "skipped"`` и причина непустая:
    «почему этап закрыт без работы» — вопрос, на который отвечает сам прогресс.
    Позиция при этом выполнена целиком: «задача закрыта = все этапы закрыты».
    """
    product = await _make_product(session, sku="SKIP-DONE")
    stock, prod, route, stages = await _make_route(session, prefix="SKIP-DONE")
    plan = await _make_plan(session, prefix="SKIP-DONE")
    position, lines, _tasks = await _add_position(
        session,
        plan=plan,
        route=route,
        sections=[stock, prod],
        stages=stages,
        product=product,
        quantity=Decimal("100"),
        status=PlanPositionStatus.released,
        task_statuses=[WorkTaskStatus.ready, WorkTaskStatus.ready],
        extra_tasks=[(0, WorkTaskStatus.completed)],
    )

    assert (await _planning_row(client, position.id))["is_completed"] is False

    # ``skip_stage`` берёт первое задание строки: на первом этапе оно остаётся
    # открытым, второе уже выполнено — этап выходит смешанным.
    await skip_stage(session, section_plan_line_id=lines[0].id, reason="Заготовка с участка")
    await skip_stage(
        session, section_plan_line_id=lines[1].id, reason=SKIP_REASON_MATERIAL_READY
    )

    assert (await _planning_row(client, position.id))["is_completed"] is True

    stages_out = (await _position_card(client, position.id))["stages"]
    assert [stage["sequence"] for stage in stages_out] == [1, 2]
    assert [stage["task_status"] for stage in stages_out] == ["completed", "skipped"]
    assert stages_out[1]["skip_reason"] == SKIP_REASON_MATERIAL_READY
    assert stages_out[0]["skip_reason"] == "Заготовка с участка"


async def test_skip_stage_rejects_an_already_completed_stage(session: AsyncSession) -> None:
    """Выполненный этап пропустить нельзя — он уже закрыт работой.

    Отказ не должен менять состояние: этап остаётся выполненным.
    """
    product = await _make_product(session, sku="SKIP-DONE2")
    stock, prod, route, stages = await _make_route(session, prefix="SKIP-DONE2")
    plan = await _make_plan(session, prefix="SKIP-DONE2")
    _position, lines, tasks = await _add_position(
        session,
        plan=plan,
        route=route,
        sections=[stock, prod],
        stages=stages,
        product=product,
        quantity=Decimal("100"),
        task_statuses=[WorkTaskStatus.completed, WorkTaskStatus.completed],
    )

    with pytest.raises(ValueError, match="Выполненный этап нельзя пропустить"):
        await skip_stage(session, section_plan_line_id=lines[1].id)

    assert (await _stored_task(session, tasks[1].id)).status == WorkTaskStatus.completed


async def test_skip_stage_rejects_an_already_cancelled_stage(session: AsyncSession) -> None:
    """Отменённый этап пропустить нельзя — отмена не переигрывается.

    Отказ не должен менять состояние: этап остаётся отменённым.
    """
    product = await _make_product(session, sku="SKIP-CANC")
    stock, prod, route, stages = await _make_route(session, prefix="SKIP-CANC")
    plan = await _make_plan(session, prefix="SKIP-CANC")
    _position, lines, tasks = await _add_position(
        session,
        plan=plan,
        route=route,
        sections=[stock, prod],
        stages=stages,
        product=product,
        quantity=Decimal("100"),
        task_statuses=[WorkTaskStatus.completed, WorkTaskStatus.cancelled],
    )

    with pytest.raises(ValueError, match="Отменённый этап нельзя пропустить"):
        await skip_stage(session, section_plan_line_id=lines[1].id)

    assert (await _stored_task(session, tasks[1].id)).status == WorkTaskStatus.cancelled


async def test_skip_stage_requires_a_reason(session: AsyncSession) -> None:
    """Пропуск без причины отклоняется: «почему пропустили» — часть факта.

    Пустая и пробельная причина одинаково бессмысленны; этап при этом
    остаётся в прежнем состоянии.
    """
    product = await _make_product(session, sku="SKIP-NOREASON")
    stock, prod, route, stages = await _make_route(session, prefix="SKIP-NOREASON")
    plan = await _make_plan(session, prefix="SKIP-NOREASON")
    _position, lines, tasks = await _add_position(
        session,
        plan=plan,
        route=route,
        sections=[stock, prod],
        stages=stages,
        product=product,
        quantity=Decimal("100"),
        task_statuses=[WorkTaskStatus.completed, WorkTaskStatus.ready],
    )

    with pytest.raises(ValueError, match="требует причины"):
        await skip_stage(session, section_plan_line_id=lines[1].id, reason="   ")

    assert (await _stored_task(session, tasks[1].id)).status == WorkTaskStatus.ready


async def test_skipped_stage_does_not_hold_demand_in_the_stock_indicator(
    client, session: AsyncSession
) -> None:
    """Пропущенный этап не держит позицию открытой для индикатора остатка.

    Остаток 1500. Позиция на 400 шт. (первый этап выполнен, второй
    пропущен) материал не занимает: у пропущенного этапа материала не было.
    Наблюдаем со стороны ещё не запущенной позиции на 100 шт. Спрос
    запущенных равен 300 (только открытое задание), собственный спрос
    наблюдателя вычитается же — 100, поэтому занято ``300 − 100 = 200`` и
    доступно ``1500 − 200 = 1300``. Если бы пропущенная позиция держала
    спрос, было бы ``1500 − 600 = 900``.
    """
    product = await _make_product(session, sku="SKIP-DEMAND")
    stock, prod, route, stages = await _make_route(session, prefix="SKIP-DEMAND")
    plan = await _make_plan(session, prefix="SKIP-DEMAND")
    await StockCommandService().record(
        session,
        StockCommand(
            product_id=product.id,
            to_location_id=stock.id,
            quantity=Decimal("1500"),
            reason=Reason.MANUAL_IN,
            created_by=1,
        ),
    )
    await session.commit()

    _skipped_position, lines, _tasks = await _add_position(
        session,
        plan=plan,
        route=route,
        sections=[stock, prod],
        stages=stages,
        product=product,
        quantity=Decimal("400"),
        status=PlanPositionStatus.released,
        task_statuses=[WorkTaskStatus.completed, WorkTaskStatus.ready],
    )
    await skip_stage(session, section_plan_line_id=lines[1].id)
    _open_position, _lines, _tasks2 = await _add_position(
        session,
        plan=plan,
        route=route,
        sections=[stock, prod],
        stages=stages,
        product=product,
        quantity=Decimal("300"),
        status=PlanPositionStatus.released,
        task_statuses=[WorkTaskStatus.completed, WorkTaskStatus.ready],
    )
    not_started, _lines3, _tasks3 = await _add_position(
        session,
        plan=plan,
        route=route,
        sections=[stock, prod],
        stages=stages,
        product=product,
        quantity=Decimal("100"),
        task_statuses=[WorkTaskStatus.completed, WorkTaskStatus.ready],
    )

    row = await _planning_row(client, not_started.id)
    assert row["free_stock_quantity"] == 1500.0
    assert row["available_remainder_quantity"] == 1300.0


async def _planning_row(client, position_id: int) -> dict:
    resp = await client.get("/api/production-planning/rows?limit=500")
    assert resp.status_code == 200, resp.text
    return next(
        row for row in resp.json()["rows"] if row["plan_position_id"] == position_id
    )


async def _position_card(client, position_id: int) -> dict:
    resp = await client.get(f"/api/production-planning/rows/{position_id}")
    assert resp.status_code == 200, resp.text
    return resp.json()
