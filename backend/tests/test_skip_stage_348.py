"""Ручной пропуск этапа из интерфейса (тикет #348).

Решение владельца: пропускать этап вручную может **только** admin и
section_manager, причина обязательна, каждое действие попадает в аудит.

Защищаемые контракты, каждый — отдельный тест:

* operator/viewer/transporter получают 403 и не меняют состояние этапа;
* пустая (и пробельная) причина — 400, этап остаётся открытым;
* section_manager пропускает этап: задание получает ``skipped`` с причиной,
  а в аудит пишется кто, какое задание/этап и зачем;
* уже выполненный этап пропустить нельзя — внятный отказ, состояние прежнее;
* из нескольких заданий одной строки пропускается ровно запрошенное.
"""

from __future__ import annotations

import pytest
from app.core.config import settings
from app.models.audit_log import AuditAction, AuditEntityType, AuditLog
from app.models.internal_plan import SectionPlanLine
from app.models.user import UserRole
from app.models.work_task import WorkTask, WorkTaskStatus
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from tests.helpers.auth import user_headers
from tests.helpers.completed_operations import build_operation_route

STAGES = [("Склад", "raw_stock", ["ISSUE"]), ("Цех", "production", ["DRILL"])]

REASON = "Материал подан в готовом виде"


def skip_url(task_id: int) -> str:
    return f"/api/shopfloor/tasks/{task_id}/skip"


@pytest.fixture(autouse=True)
def _strict_auth(monkeypatch: pytest.MonkeyPatch) -> None:
    """Тест проверяет роли — только strict-режим.

    В dev-ветке запрос без токена достаётся ``system@local`` (admin), и 403
    не отличить от «гейт пропустил».
    """
    monkeypatch.setattr(settings, "DEV_BYPASS_AUTH", False)


async def _make_stage_pair(session: AsyncSession, sku: str) -> dict:
    return await build_operation_route(session, sku=sku, stages=STAGES)


async def _stored_task(session: AsyncSession, task_id: int) -> WorkTask:
    """Задание из базы, а не из кэша сессии: проверяем сохранённые значения."""
    session.expire_all()
    task = await session.get(WorkTask, task_id)
    assert task is not None
    return task


async def test_operator_viewer_and_transporter_cannot_skip_a_stage(
    client, session: AsyncSession
) -> None:
    """Пропуск — решение старшего: три роли без права получают 403.

    Отказ не должен менять состояние этапа: задание остаётся открытым.
    """
    fx = await _make_stage_pair(session, "SKIP-403")
    task = fx["tasks"][1]

    for role, username in (
        (UserRole.operator, "skip_operator"),
        (UserRole.viewer, "skip_viewer"),
        (UserRole.transporter, "skip_transporter"),
    ):
        _, headers = await user_headers(session, role, username)
        response = await client.post(
            skip_url(task.id), json={"reason": REASON}, headers=headers
        )
        assert response.status_code == 403, f"{role.value}: {response.text}"

    stored = await _stored_task(session, task.id)
    assert stored.status == WorkTaskStatus.in_progress
    assert stored.skip_reason is None


async def test_empty_reason_is_rejected(client, session: AsyncSession) -> None:
    """Причина обязательна: пустая и пробельная одинаково бессмысленны."""
    fx = await _make_stage_pair(session, "SKIP-EMPTY")
    task = fx["tasks"][1]
    _, headers = await user_headers(session, UserRole.section_manager, "skip_empty")

    for reason in ("", "   "):
        response = await client.post(
            skip_url(task.id), json={"reason": reason}, headers=headers
        )
        assert response.status_code == 400, response.text
        assert "причин" in response.json()["detail"].lower()

    stored = await _stored_task(session, task.id)
    assert stored.status == WorkTaskStatus.in_progress
    assert stored.skip_reason is None


async def test_section_manager_skips_the_stage_and_the_action_is_audited(
    client, session: AsyncSession
) -> None:
    """Успешный пропуск: статус ``skipped`` с причиной и запись в аудите.

    Аудит — единственная система журнала (``audit_logs``): строка называет
    автора, задание и этап, а причина сохраняется и в сообщении, и в
    ``comment``.
    """
    fx = await _make_stage_pair(session, "SKIP-OK")
    task = fx["tasks"][1]
    task_id, task_section_id = task.id, task.section_id
    manager, headers = await user_headers(
        session, UserRole.section_manager, "skip_manager"
    )
    manager_id = manager.id

    response = await client.post(
        skip_url(task_id), json={"reason": REASON}, headers=headers
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["task_id"] == task_id
    assert body["status"] == WorkTaskStatus.skipped.value
    assert body["skip_reason"] == REASON

    stored = await _stored_task(session, task_id)
    assert stored.status == WorkTaskStatus.skipped
    assert stored.skip_reason == REASON

    logs = (
        (
            await session.execute(
                select(AuditLog).where(
                    AuditLog.action == AuditAction.SKIP.value,
                    AuditLog.entity_type == AuditEntityType.WORK_TASK.value,
                    AuditLog.entity_id == task_id,
                )
            )
        )
        .scalars()
        .all()
    )
    assert len(logs) == 1, "пропуск пишется в аудит ровно одной строкой"
    log = logs[0]
    assert log.user_id == manager_id
    assert log.comment == REASON
    assert REASON in log.message
    assert log.section_id == task_section_id
    assert log.task_ids == str(task_id)


async def test_already_completed_stage_cannot_be_skipped(
    client, session: AsyncSession
) -> None:
    """Выполненный этап пропустить нельзя — отказ с понятным текстом."""
    fx = await _make_stage_pair(session, "SKIP-DONE")
    task = fx["tasks"][1]
    task.status = WorkTaskStatus.completed
    await session.commit()
    _, headers = await user_headers(session, UserRole.admin, "skip_done_admin")

    response = await client.post(
        skip_url(task.id), json={"reason": REASON}, headers=headers
    )
    assert response.status_code == 400, response.text
    assert "Выполненный этап нельзя пропустить" in response.json()["detail"]

    stored = await _stored_task(session, task.id)
    assert stored.status == WorkTaskStatus.completed
    assert stored.skip_reason is None


async def test_only_the_requested_task_of_a_line_is_skipped(
    client, session: AsyncSession
) -> None:
    """На строке с двумя заданиями пропускается ровно запрошенное.

    Этап закрывается результатом только когда закрыты все его задания,
    поэтому «пропустить первое попавшееся задание строки» было бы подменой
    выбора оператора.
    """
    fx = await _make_stage_pair(session, "SKIP-TWIN")
    line: SectionPlanLine = fx["plan_lines"][1]
    first_task_id = fx["tasks"][1].id
    twin = WorkTask(
        section_plan_line_id=line.id,
        section_id=line.section_id,
        product_id=line.product_id,
        route_stage_id=line.route_stage_id,
        planned_quantity=line.planned_quantity,
        status=WorkTaskStatus.in_progress,
    )
    session.add(twin)
    await session.commit()
    twin_id = twin.id

    _, headers = await user_headers(session, UserRole.section_manager, "skip_twin")
    response = await client.post(
        skip_url(twin_id), json={"reason": REASON}, headers=headers
    )
    assert response.status_code == 200, response.text

    assert (await _stored_task(session, twin_id)).status == WorkTaskStatus.skipped
    first = await _stored_task(session, first_task_id)
    assert first.status == WorkTaskStatus.in_progress, "чужое задание не тронуто"
    assert first.skip_reason is None
