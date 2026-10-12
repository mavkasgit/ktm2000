"""Инвариант «порция факта»: ledger → проекция строки участка → статус (#320).

Три пути записи порции (завершение, возврат остатка, выпуск) сведены к одной
точке ``operations_tasks.apply_ledger_portion`` (проекция строки участка);
статус задания в каждой проводке пишет ``StockCommandService.record``
(ADR-0041). Здесь проверяются те два, которые до этого жили мимо неё:

* ``POST /shopfloor/remainders/return`` — тело перенесено из роута в пакет,
  после проводки обновляется проекция строки участка, статус синхронизирует
  record();
* ``defect_decide`` — решение по браку меняет rejected, то есть вход
  проекции статуса, поэтому статус пересчитывается;
* ``final_release`` — FINAL_RELEASE в проекцию статуса не входит (шаг
  «применить порцию» там no-op) — это доказано равенством проекции до/после.
"""

from __future__ import annotations

from decimal import Decimal

import pytest
from app.models.defect import DefectDecisionType
from app.models.internal_plan import SectionPlanLine
from app.models.work_task import WorkTaskStatus
from app.services.shopfloor.operations_defects import create_defect, defect_decide
from app.services.shopfloor.operations_tasks import final_release
from app.services.shopfloor.task_status import sync_work_task_status
from app.stock import Reason, StockCommand, StockCommandService
from app.stock.models import StockTransaction
from app.stock.services import StockProjectionManager
from app.stock.task_cache import compute_task_available
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from tests.stock.helpers import (
    FAKE_DEFECT_DECISION_MAP,
    record_transfer_receive,
)
from tests.stock.test_shopfloor_stage3 import (
    _consume_ops,
    _seed_raw_stock,
    _setup_minimal_route,
)
from tests.test_integrity_invariants import assert_no_stock_ledger_invariants_violations

pytestmark = pytest.mark.asyncio

PLANNED = Decimal(100)


async def _task_with_issued(
    session: AsyncSession, *, sku: str, issued: Decimal, planned: Decimal = PLANNED
) -> dict:
    """Задание участка с выданным материалом: issued задаёт TRANSFER_RECEIVE."""
    fx = await _setup_minimal_route(session, sku=sku, qty=planned)
    await _seed_raw_stock(session, fx, quantity=planned)
    await record_transfer_receive(
        session,
        product_id=fx["product"].id,
        from_location_id=fx["raw"].id,
        to_location_id=fx["task"].section_id,
        quantity=issued,
        task_id=fx["task"].id,
        completed_operations=await _consume_ops(session, fx),
        created_by=fx["user"].id,
    )
    await session.commit()
    return fx


async def test_return_remainder_updates_line_cache_and_status(
    session: AsyncSession, auth_client
) -> None:
    """Возврат остатка обновляет проекцию строки участка и статус задания.

    До вызова статус задания — ``in_progress``: выдача (``record`` с
    ``task_id``) уже синхронизировала его в своей транзакции. Возврат же
    остатка шёл из роута мимо ``apply_ledger_portion`` — теперь статус
    выводится из ledger и здесь.
    """
    fx = await _task_with_issued(session, sku="RTR320", issued=Decimal(10))
    task = fx["task"]
    line = await session.get(SectionPlanLine, task.section_plan_line_id)
    assert task.status == WorkTaskStatus.in_progress, (
        "выдача через write-path синхронизирует статус сама"
    )

    resp = await auth_client.post(
        "/api/shopfloor/remainders/return",
        json={"task_id": task.id, "quantity": "3", "comment": "остаток"},
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["status"] == WorkTaskStatus.in_progress.value

    await session.commit()
    await session.refresh(task)
    await session.refresh(line)

    # Статус выведен из ledger: выдача есть (issued=10) → in_progress.
    assert task.status == WorkTaskStatus.in_progress

    # Проекция строки участка пересчитана из ledger вместе с возвратом:
    # available = planned + received + returned − issued = 100 + 10 + 3 − 10.
    assert line.cached_available_quantity == compute_task_available(
        planned_quantity=PLANNED,
        received_quantity=Decimal(10),
        issued_quantity=Decimal(10),
        returned_quantity=Decimal(3),
        is_first_stage=True,
    )

    returned = await session.scalar(
        select(func.sum(StockTransaction.quantity)).where(
            StockTransaction.task_id == task.id,
            StockTransaction.reason == Reason.RETURN_TO_STOCK,
        )
    )
    assert returned == Decimal(3)

    await assert_no_stock_ledger_invariants_violations(session, context="return-remainder-320")


async def test_defect_decide_syncs_task_status(session: AsyncSession) -> None:
    """Решение по браку пересчитывает статус: порция входит в проекцию.

    Ветка ``accept_with_deviation`` пишет COMPLETE — это ``completed_quantity``
    проекции задания, то есть вход ``resolve_work_task_status``; остальные три
    ветки меняют rejected/rework тем же способом. До решения статус задания
    был ``in_progress`` (выдача синхронизировала его в write-path), а
    ``defect_decide`` звал только проекцию строки.
    """
    fx = await _task_with_issued(session, sku="DDS320", issued=Decimal(10))
    task = fx["task"]
    line = await session.get(SectionPlanLine, task.section_plan_line_id)
    assert task.status == WorkTaskStatus.in_progress, (
        "выдача через write-path синхронизирует статус сама"
    )

    created = await create_defect(
        session,
        task_id=task.id,
        quantity=Decimal(4),
        actor_id=fx["user"].id,
        reason="brak",
    )
    await session.commit()

    await defect_decide(
        session,
        defect_id=created["defect_id"],
        decision_type=DefectDecisionType.accept_with_deviation,
        quantity=Decimal(4),
        actor_id=fx["user"].id,
        idempotency_key="dds320-accept",
        defect_decision_map=FAKE_DEFECT_DECISION_MAP,
    )
    await session.commit()
    await session.refresh(task)
    await session.refresh(line)

    # produced = completed = 4 из 100 → задание частично выполнено.
    assert task.status == WorkTaskStatus.partially_completed
    assert line.cached_completed_quantity == Decimal(4)

    await assert_no_stock_ledger_invariants_violations(session, context="defect-decide-320")


async def test_final_release_keeps_task_status(session: AsyncSession) -> None:
    """FINAL_RELEASE не входит в проекцию статуса — выпуск её не двигает.

    Замер: проекция задания (все 7 полей, из которых выводится статус)
    до и после выпуска совпадает — значит шаг «применить порцию» здесь
    no-op доменно, а не «на всякий случай».
    """
    fx = await _task_with_issued(session, sku="FR320", issued=Decimal(10), planned=Decimal(10))
    task = fx["task"]

    await StockCommandService().record(session, StockCommand(
        product_id=fx["product"].id,
        from_location_id=None,
        to_location_id=task.section_id,
        quantity=Decimal(8),
        reason=Reason.COMPLETE,
        task_id=task.id,
        created_by=fx["user"].id,
    ))
    await session.commit()

    # Базовая линия — статус, выведенный доменом из ledger ДО выпуска.
    await sync_work_task_status(session, task)
    await session.commit()
    status_before = task.status
    assert status_before == WorkTaskStatus.partially_completed, "выведено из ledger, не выставлено руками"

    cache_before = await StockProjectionManager().get_task_cache(session, task.id)

    await final_release(
        session,
        task_id=task.id,
        quantity=Decimal(8),
        actor_id=fx["user"].id,
    )
    await session.commit()
    await session.refresh(task)

    cache_after = await StockProjectionManager().get_task_cache(session, task.id)
    assert cache_after == cache_before, "выпуск не меняет проекцию задания"
    assert task.status == status_before

    released = await session.scalar(
        select(func.count())
        .select_from(StockTransaction)
        .where(
            StockTransaction.task_id == task.id,
            StockTransaction.reason == Reason.FINAL_RELEASE,
        )
    )
    assert released == 1

    await assert_no_stock_ledger_invariants_violations(session, context="final-release-320")
