"""Принудительное удаление батча импорта поверх живых данных.

Контракт, который защищают тесты: снос поддерева батча возвращает склад к
состоянию до импорта (ledger → баланс, S1), оставляет запись в журнале
действий и аудит-логе, и при этом не трогает то, что принадлежит чужому
импорту (передача через границу батча).
"""

from __future__ import annotations

from decimal import Decimal

import pytest
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.action_journal import Action, ActionStatus
from app.models.audit_log import AuditLog
from app.models.imports import ImportBatch, ImportBatchMode
from app.models.production_plan import PlanChangeSet, PlanPosition, PlanPositionStatus
from app.models.internal_plan import SectionPlanLine
from app.models.transfer import Transfer
from app.models.work_task import WorkTask, WorkTaskStatus
from app.services.action_journal_service import action_journal_service
from app.services.import_batch_force_delete import get_batch_force_delete_preview
from app.stock.models import QualityState, StockBalance, StockTransaction
from tests.test_batch_delete_409 import (
    _make_change_set,
    _make_plan_file_batch,
    _make_position,
    _make_position_line,
    _make_product,
    _make_transfer_chain,
)
from tests.test_integrity_invariants import assert_no_invariants_violations

pytestmark = pytest.mark.asyncio


async def _balance(session: AsyncSession, product_id: int, location_id: int) -> Decimal:
    return (
        await session.scalar(
            select(func.coalesce(func.sum(StockBalance.balance_qty), 0)).where(
                StockBalance.product_id == product_id,
                StockBalance.location_id == location_id,
                StockBalance.quality_state == QualityState.GOOD,
            )
        )
    ) or Decimal("0")


async def _balance_locations(session: AsyncSession, product_id: int) -> list[int]:
    return list(
        (
            await session.execute(
                select(StockBalance.location_id).where(
                    StockBalance.product_id == product_id
                )
            )
        ).scalars()
    )


async def _transaction_locations(session: AsyncSession, product_id: int) -> list[int]:
    """Все локации, которых касался ledger по артикулу: строки баланса после
    сноса пересоздаются, поэтому опираться на них нельзя."""
    rows = await session.execute(
        select(StockTransaction.from_location_id, StockTransaction.to_location_id).where(
            StockTransaction.product_id == product_id
        )
    )
    return sorted({loc for pair in rows for loc in pair if loc is not None})


async def _build_released_batch_with_transfer(session: AsyncSession, tag: str) -> dict:
    """Батч, который обычным DELETE удалить нельзя: released + передача вниз."""
    product = await _make_product(session, tag)
    plan, batch = await _make_plan_file_batch(session, tag)
    position = _make_position(
        session, plan, product, batch, status=PlanPositionStatus.released, row=2
    )
    await session.flush()
    transfer = await _make_transfer_chain(session, plan, product, position, tag=tag)
    change_set = await _make_change_set(session, plan, batch, [position], applied=True)
    await session.commit()
    task_ids = list(
        (
            await session.execute(
                select(WorkTask.id).where(
                    WorkTask.product_id == product.id
                )
            )
        ).scalars()
    )
    return {
        "product": product,
        "plan": plan,
        "batch": batch,
        "position": position,
        "transfer": transfer,
        "change_set": change_set,
        "task_ids": task_ids,
    }


async def test_force_delete_preview_counts_footprint_and_stock_effects(
    session: AsyncSession, client
) -> None:
    fx = await _build_released_batch_with_transfer(session, "BFD-PREVIEW")
    product, plan, batch = fx["product"], fx["plan"], fx["batch"]

    resp = await client.get(
        f"/api/production-plans/{plan.id}/batches/{batch.id}/force-delete-preview"
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["filename"] == "BFD-PREVIEW.xlsx"
    assert body["positions"] == 1
    assert body["section_plan_lines"] == 2
    assert body["work_tasks"] == 2
    assert body["transfers"] == 1
    # Ручной приход фикстуры не привязан к батчу, в снос не входит: только
    # SEND+RECEIVE, порождённые передачей.
    assert body["ledger_entries"] == 2
    assert body["blockers"] == []

    # SEND уводит 5 с участка-источника и приводит 5 на следующий: превью
    # обязано показать оба плеча, иначе оператор не видит ухода со склада.
    deltas = {e["location_id"]: e["net_delta"] for e in body["stock_effects"]}
    assert sorted(deltas.values()) == ["-5.000", "5.000"], body["stock_effects"]
    assert await _balance(session, product.id, next(iter(deltas))) is not None


async def test_force_delete_removes_graph_and_returns_stock_to_pre_import(
    session: AsyncSession, client
) -> None:
    fx = await _build_released_batch_with_transfer(session, "BFD-DEL")
    product, plan, batch = fx["product"], fx["plan"], fx["batch"]
    position, transfer = fx["position"], fx["transfer"]
    task_ids, change_set_id = fx["task_ids"], fx["change_set"].id
    locations = await _transaction_locations(session, product.id)
    # До сноса материал лежит только на следующем участке: источник отдал 5
    # из 5 и обнулился.
    before = {loc: await _balance(session, product.id, loc) for loc in locations}
    assert sorted(before.values()) == [Decimal("0.000"), Decimal("5.000")], before

    resp = await client.request(
        "DELETE",
        f"/api/production-plans/{plan.id}/batches/{batch.id}/force",
        json={"confirmation": "BFD-DEL.xlsx", "reason": "импорт был ошибочным"},
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["deleted"] is True
    assert body["mode"] == "force"
    assert body["positions"] == 1
    assert body["transfers"] == 1
    assert body["history_action_id"]

    assert await session.get(PlanPosition, position.id) is None
    assert await session.get(Transfer, transfer.id) is None
    assert await session.get(PlanChangeSet, change_set_id) is None
    assert await session.get(ImportBatch, batch.id) is None
    for task_id in task_ids:
        assert await session.get(WorkTask, task_id) is None
    assert (
        await session.scalar(
            select(func.count(StockTransaction.id)).where(
                StockTransaction.task_id.in_(task_ids)
            )
        )
    ) == 0

    # Возврат к состоянию до импорта: остатки просто поменялись местами —
    # у участка-источника материал вернулся (уходившая по батчу проводка
    # снесена), на следующем исчез (приход по передаче батча снесён).
    after = {loc: await _balance(session, product.id, loc) for loc in locations}
    source, target = locations
    assert after == {source: before[target], target: before[source]}, (before, after)

    history = await session.get(Action, body["history_action_id"])
    assert history.action_type == "import_batch_force_delete"
    assert history.reason == "импорт был ошибочным"
    audit = await session.scalar(
        select(AuditLog).where(
            AuditLog.entity_type == "import_batch",
            AuditLog.entity_id == batch.id,
            AuditLog.action == "delete",
        )
    )
    assert audit is not None
    assert "импорт был ошибочным" in audit.message
    assert audit.changes["before"]["transfers"] == 1

    await assert_no_invariants_violations(session, context="batch-force-delete")


async def test_force_delete_requires_exact_filename_and_reason(
    session: AsyncSession, client
) -> None:
    fx = await _build_released_batch_with_transfer(session, "BFD-GUARD")
    plan, batch, position = fx["plan"], fx["batch"], fx["position"]

    wrong = await client.request(
        "DELETE",
        f"/api/production-plans/{plan.id}/batches/{batch.id}/force",
        json={"confirmation": "wrong.xlsx", "reason": "ошибочный импорт"},
    )
    assert wrong.status_code == 400
    short = await client.request(
        "DELETE",
        f"/api/production-plans/{plan.id}/batches/{batch.id}/force",
        json={"confirmation": "BFD-GUARD.xlsx", "reason": "  "},
    )
    assert short.status_code == 400
    assert await session.get(PlanPosition, position.id) is not None
    assert await session.get(Transfer, fx["transfer"].id) is not None
    await assert_no_invariants_violations(session, context="batch-force-delete-guard")


async def test_force_delete_refuses_transfer_crossing_batch_boundary(
    session: AsyncSession, client
) -> None:
    """Передача связала батч с чужим импортом: снести её — испортить чужое."""
    fx = await _build_released_batch_with_transfer(session, "BFD-X")
    plan, batch, position = fx["plan"], fx["batch"], fx["position"]
    foreign_product = await _make_product(session, "BFD-XF")
    other_batch = ImportBatch(
        source_file_id=batch.source_file_id,
        production_plan_id=plan.id,
        mode=ImportBatchMode.create_plan,
        sheet_name="Чужой",
        header_row_number=1,
        total_rows=1,
        parsed_rows=1,
        summary={},
    )
    session.add(other_batch)
    await session.flush()
    foreign_position = _make_position(
        session, plan, foreign_product, other_batch,
        status=PlanPositionStatus.approved, row=9,
    )
    await session.flush()
    await _make_position_line(
        session, plan, foreign_product, foreign_position, tag="BFD-XF"
    )
    foreign_line = (
        await session.execute(
            select(SectionPlanLine).where(
                SectionPlanLine.plan_position_id == foreign_position.id
            )
        )
    ).scalar_one()
    foreign_task = WorkTask(
        section_plan_line_id=foreign_line.id,
        section_id=foreign_line.section_id,
        product_id=foreign_product.id,
        route_stage_id=foreign_line.route_stage_id,
        planned_quantity=Decimal("1"),
        status=WorkTaskStatus.ready,
    )
    session.add(foreign_task)
    await session.flush()
    # Перешиваем получателя передачи на задание чужого батча.
    transfer = await session.get(Transfer, fx["transfer"].id)
    transfer.to_task_id = foreign_task.id
    await session.commit()

    preview = await get_batch_force_delete_preview(session, batch.id)
    assert any(
        "transfer-crosses-batch" in b["reason"] for b in preview["blockers"]
    ), preview["blockers"]

    resp = await client.request(
        "DELETE",
        f"/api/production-plans/{plan.id}/batches/{batch.id}/force",
        json={"confirmation": "BFD-X.xlsx", "reason": "хочу снести батч"},
    )
    assert resp.status_code == 409, resp.text
    body = resp.json()
    assert body["code"] == "batch_force_delete_blocked"
    assert any("transfer-crosses-batch" in b["reason"] for b in body["blockers"])
    assert await session.get(PlanPosition, position.id) is not None
    assert await session.get(Transfer, fx["transfer"].id) is not None
    assert await session.get(PlanPosition, foreign_position.id) is not None
    await assert_no_invariants_violations(session, context="batch-force-delete-crossing")


async def test_force_delete_marks_batch_actions_purged_but_keeps_journal(
    session: AsyncSession, client
) -> None:
    """Проводки стёрты, но записи журнала остаются как аудит (ADR-0019 п.7)."""
    fx = await _build_released_batch_with_transfer(session, "BFD-PURGE")
    plan, batch = fx["plan"], fx["batch"]
    action = await action_journal_service.log_task_action(
        session,
        action_type="task_complete",
        ref_id=fx["task_ids"][0],
        actor="fixture",
    )
    await session.commit()
    action_id = action.id

    resp = await client.request(
        "DELETE",
        f"/api/production-plans/{plan.id}/batches/{batch.id}/force",
        json={"confirmation": "BFD-PURGE.xlsx", "reason": "чистка демо-импорта"},
    )
    assert resp.status_code == 200, resp.text
    assert action_id in resp.json()["purged_action_ids"]

    stored = await session.get(Action, action_id)
    assert stored is not None, "журнал действий не удаляется"
    assert stored.status == ActionStatus.PURGED
    await assert_no_invariants_violations(session, context="batch-force-delete-purge")


async def test_force_delete_batch_without_positions_is_400(
    session: AsyncSession, client
) -> None:
    plan, batch = await _make_plan_file_batch(session, "BFD-404")
    await session.commit()

    resp = await client.request(
        "DELETE",
        f"/api/production-plans/{plan.id}/batches/{batch.id}/force",
        json={"confirmation": "BFD-404.xlsx", "reason": "нет позиций"},
    )
    assert resp.status_code == 400
    assert "no positions" in resp.json()["detail"]
    assert await session.get(ImportBatch, batch.id) is not None
