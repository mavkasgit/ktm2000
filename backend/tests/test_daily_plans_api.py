"""HTTP contract tests for section daily plans.

These tests exercise the public API and use the existing shopfloor route fixture
as the async-session seam for arranging real WorkTask topology.
"""
from __future__ import annotations

from datetime import date

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.audit_log import AuditLog
from app.models.work_task import WorkTask, WorkTaskStatus
from tests.stock.test_shopfloor_stage3 import _setup_minimal_route

pytestmark = pytest.mark.asyncio

PLAN_DATE = date(2026, 9, 24)


async def _create_plan(auth_client, task_id: int, section_id: int) -> dict:
    response = await auth_client.post(
        "/api/daily-plans",
        json={
            "section_id": section_id,
            "plan_date": PLAN_DATE.isoformat(),
            "work_task_ids": [task_id],
        },
    )
    assert response.status_code == 201, response.text
    return response.json()


async def test_same_date_plans_are_allowed(
    auth_client, session: AsyncSession
) -> None:
    first = await _setup_minimal_route(session, sku="DP-SAME-1")
    second = await _setup_minimal_route(session, sku="DP-SAME-2")

    first_response = await auth_client.post(
        "/api/daily-plans",
        json={
            "section_id": first["task"].section_id,
            "plan_date": PLAN_DATE.isoformat(),
            "work_task_ids": [first["task"].id],
        },
    )
    second_response = await auth_client.post(
        "/api/daily-plans",
        json={
            "section_id": second["task"].section_id,
            "plan_date": PLAN_DATE.isoformat(),
            "work_task_ids": [second["task"].id],
        },
    )

    assert first_response.status_code == 201, first_response.text
    assert second_response.status_code == 201, second_response.text
    first_plan = first_response.json()
    second_plan = second_response.json()
    assert first_plan["id"] != second_plan["id"]
    assert first_plan["plan_date"] == PLAN_DATE.isoformat()
    assert second_plan["plan_date"] == PLAN_DATE.isoformat()

async def test_create_empty_daily_plan(auth_client, session: AsyncSession) -> None:
    fixture = await _setup_minimal_route(session, sku="DP-EMPTY")
    response = await auth_client.post(
        "/api/daily-plans",
        json={
            "section_id": fixture["task"].section_id,
            "plan_date": PLAN_DATE.isoformat(),
            "work_task_ids": [],
        },
    )
    assert response.status_code == 201, response.text
    plan = response.json()
    assert plan["item_count"] == 0
    assert plan["progress_percent"] == 0
    items = await auth_client.get(f"/api/daily-plans/{plan['id']}/items")
    assert items.status_code == 200, items.text
    assert items.json()["items"] == []


async def test_create_rejects_completed_task(
    auth_client, session: AsyncSession
) -> None:
    fixture = await _setup_minimal_route(session, sku="DP-COMPLETED")
    fixture["task"].status = WorkTaskStatus.completed
    await session.commit()

    response = await auth_client.post(
        "/api/daily-plans",
        json={
            "section_id": fixture["task"].section_id,
            "plan_date": PLAN_DATE.isoformat(),
            "work_task_ids": [fixture["task"].id],
        },
    )

    assert response.status_code == 422, response.text
    assert "terminal" in response.json()["detail"].lower()

async def test_create_rejects_task_in_another_active_plan(
    auth_client, session: AsyncSession
) -> None:
    fixture = await _setup_minimal_route(session, sku="DP-CONFLICT")
    first_plan = await _create_plan(auth_client, fixture["task"].id, fixture["task"].section_id)

    response = await auth_client.post(
        "/api/daily-plans",
        json={
            "section_id": fixture["task"].section_id,
            "plan_date": PLAN_DATE.isoformat(),
            "work_task_ids": [fixture["task"].id],
        },
    )

    assert response.status_code == 409, response.text
    first_items = await auth_client.get(
        f"/api/daily-plans/{first_plan['id']}/items"
    )
    assert first_items.status_code == 200, first_items.text
    assert [item["work_task_id"] for item in first_items.json()["items"]] == [
        fixture["task"].id
    ]


async def test_composition_keeps_completed_work_task(
    auth_client, session: AsyncSession
) -> None:
    fixture = await _setup_minimal_route(session, sku="DP-COMPOSITION")
    plan = await _create_plan(auth_client, fixture["task"].id, fixture["task"].section_id)
    fixture["task"].status = WorkTaskStatus.completed
    await session.commit()

    response = await auth_client.get(f"/api/daily-plans/{plan['id']}/items")

    assert response.status_code == 200, response.text
    items = response.json()["items"]
    assert len(items) == 1
    assert items[0]["work_task_id"] == fixture["task"].id
    assert items[0]["task"]["status"] == WorkTaskStatus.completed.value


async def test_revoke_removes_membership_preserves_task_and_audits(
    auth_client, session: AsyncSession
) -> None:
    fixture = await _setup_minimal_route(session, sku="DP-REVOKE")
    plan = await _create_plan(auth_client, fixture["task"].id, fixture["task"].section_id)
    task_id = fixture["task"].id
    before = await session.get(WorkTask, task_id)
    assert before is not None
    before_state = (before.status, before.section_id, before.planned_quantity)

    response = await auth_client.post(
        f"/api/daily-plans/{plan['id']}/items/{task_id}/revoke"
    )

    assert response.status_code == 200, response.text
    assert response.json() == {"plan_id": plan["id"], "work_task_id": task_id}
    items_response = await auth_client.get(
        f"/api/daily-plans/{plan['id']}/items"
    )
    assert items_response.status_code == 200, items_response.text
    assert items_response.json()["items"] == []

    after = await session.get(WorkTask, task_id)
    assert after is not None
    assert (after.status, after.section_id, after.planned_quantity) == before_state

    audit = await session.scalar(
        select(AuditLog).where(
            AuditLog.entity_type == "daily_plan",
            AuditLog.entity_id == plan["id"],
            AuditLog.task_ids == str(task_id),
        )
    )
    assert audit is not None
    assert audit.status == "success"
    assert audit.action == "delete"
