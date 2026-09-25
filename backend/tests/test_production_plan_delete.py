from __future__ import annotations

from decimal import Decimal

import pytest
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.action_journal import Action, ActionStatus
from app.models.audit_log import AuditLog
from app.models.internal_plan import InternalPlan, SectionPlanLine
from app.models.production_plan import (
    PlanPosition,
    PlanPositionStatus,
    ProductionPlan,
    ProductionPlanStatus,
)
from app.models.work_task import WorkTask, WorkTaskStatus
from app.services.production_plan_service import get_production_plan_delete_preview
from app.services.action_journal_service import action_journal_service
from app.stock.models import Reason, StockTransaction
from app.stock.services import StockCommand, StockCommandService
from tests.stock.test_shopfloor_stage3 import _setup_minimal_route
from tests.test_integrity_invariants import assert_no_invariants_violations

pytestmark = pytest.mark.asyncio


async def _final_release_fixture(session: AsyncSession, sku: str) -> dict:
    fx = await _setup_minimal_route(session, sku=sku, qty=Decimal("10"))
    stock = StockCommandService()
    await stock.record(
        session,
        StockCommand(
            product_id=fx["product"].id,
            to_location_id=fx["prod"].id,
            quantity=Decimal("10"),
            reason=Reason.MANUAL_IN,
            created_by=fx["user"].id,
        ),
    )
    action = await action_journal_service.log_task_action(
        session,
        action_type="final_release",
        ref_id=fx["task"].id,
        actor=fx["user"].username,
    )
    result = await stock.record(
        session,
        StockCommand(
            product_id=fx["product"].id,
            from_location_id=fx["prod"].id,
            to_location_id=fx["fg"].id,
            quantity=Decimal("3"),
            reason=Reason.FINAL_RELEASE,
            task_id=fx["task"].id,
            action_id=action.id,
            created_by=fx["user"].id,
        ),
    )
    fx["task"].status = WorkTaskStatus.completed
    task = fx["task"]
    position_id, plan_id = (
        await session.execute(
            select(SectionPlanLine.plan_position_id, InternalPlan.production_plan_id)
            .join(InternalPlan, SectionPlanLine.internal_plan_id == InternalPlan.id)
            .where(SectionPlanLine.id == task.section_plan_line_id)
        )
    ).one()
    plan = await session.get(ProductionPlan, plan_id)
    await session.commit()
    return {
        **fx,
        "plan": plan,
        "position_id": position_id,
        "result": result,
        "active_action_ids": [action.id],
    }


async def test_delete_preview_counts_graph_and_stock_effects(
    session: AsyncSession,
) -> None:
    fx = await _final_release_fixture(session, "PD-PREVIEW")
    preview = await get_production_plan_delete_preview(session, fx["plan"].id)
    preview.pop("_reversal_plans")

    assert preview["positions"] == 1
    assert preview["work_tasks"] == 1
    assert preview["transfers"] == 0
    assert preview["ledger_entries"] >= 1
    assert preview["active_actions"] == 1
    assert preview["used_positions"] == [{
        "position_id": fx["position_id"],
        "source_sku": fx["product"].sku,
        "status": "approved",
        "task_count": 1,
        "action_count": 1,
    }]
    assert preview["cancellations"]["positions"] == 1
    assert preview["cancellations"]["work_tasks"] == 1
    assert len(preview["stock_effects"]) == 1
    assert preview["stock_effects"][0]["effect"] == "reverse"
    assert preview["blockers"] == []


async def test_delete_plan_reverses_ledger_and_archives_graph(
    session: AsyncSession,
    client,
) -> None:
    fx = await _final_release_fixture(session, "PD-DELETE")
    plan = fx["plan"]
    plan.length_model_version = 1
    await session.commit()
    task_id = fx["task"].id
    original = await session.get(StockTransaction, fx["result"].id)
    original_action = await session.get(Action, original.action_id)

    response = await client.request(
        "DELETE",
        f"/api/production-plans/{plan.id}",
        json={"confirmation": plan.plan_no, "reason": "archive executed plan"},
    )

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["deleted"] is True
    assert set(body["reversed_action_ids"]) == set(fx["active_action_ids"])
    assert body["preserved_ledger_entries"] >= 2
    assert body["history_action_id"]
    assert (await session.get(PlanPosition, fx["position_id"])).deleted_at is not None

    await session.refresh(plan)
    assert plan.status == ProductionPlanStatus.cancelled
    assert plan.deleted_at is not None
    assert plan.delete_reason == "archive executed plan"
    assert (await session.get(WorkTask, task_id)).status == WorkTaskStatus.cancelled
    assert (await session.get(PlanPosition, fx["position_id"])).status == PlanPositionStatus.cancelled

    await session.refresh(original_action)
    assert original_action.status == ActionStatus.REVERSED
    await session.refresh(original)
    assert original.task_id == task_id
    compensation = await session.scalar(
        select(StockTransaction).where(StockTransaction.reverses_id == original.id)
    )
    assert compensation is not None
    assert compensation.task_id == task_id

    history = await session.get(Action, body["history_action_id"])
    assert history.action_type == "production_plan_delete"
    assert set(history.depends_on) == set(fx["active_action_ids"])
    audit = await session.scalar(
        select(AuditLog).where(
            AuditLog.entity_type == "production_plan",
            AuditLog.entity_id == plan.id,
            AuditLog.action == "delete",
        )
    )
    assert audit is not None
    assert "archive executed plan" in audit.message

    assert (await client.get(f"/api/production-plans/{plan.id}/preview")).status_code == 404
    assert all(
        item["id"] != plan.id
        for item in (await client.get("/api/production-plans")).json()
    )
    await assert_no_invariants_violations(session, context="production-plan-delete")


async def test_delete_wrong_confirmation_does_not_mutate(
    session: AsyncSession,
    client,
) -> None:
    fx = await _final_release_fixture(session, "PD-WRONG")
    plan = fx["plan"]
    action_count = await session.scalar(select(func.count(Action.id)))

    response = await client.request(
        "DELETE",
        f"/api/production-plans/{plan.id}",
        json={"confirmation": "wrong", "reason": "archive executed plan"},
    )

    assert response.status_code == 400
    await session.refresh(plan)
    assert plan.deleted_at is None
    assert plan.status == ProductionPlanStatus.approved
    assert await session.scalar(select(func.count(Action.id))) == action_count
