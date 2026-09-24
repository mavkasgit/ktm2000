"""API-регрессии issue #181 для write-путей под strict break-glass.

Каждый тест получает настоящий токен через публичный break-glass login при
``DEV_BYPASS_AUTH=false`` и проверяет результат через публичный API и фактические
ORM-записи. Идентификатор служебного пользователя намеренно не зашит.
"""
from __future__ import annotations

from decimal import Decimal

import pytest
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.models.attachment import Attachment, AttachmentLink
from app.models.audit_log import AuditAction, AuditEntityType, AuditLog
from app.models.defect import Defect, DefectDecision, DefectDecisionType, DefectItem, DefectStatus
from app.models.entity_comment import EntityComment
from app.models.production_plan import PlanPositionStatus, ProductionPlanStatus
from app.models.transfer import Transfer, TransferStatus
from app.models.user import User
from app.stock.models import Reason, StockTransaction
from tests.helpers.transfers import _make_tasks_transferable, _make_two_ghp_setup
from tests.stock.test_task_completion_transform import _make_transform_setup, _receive_input
from tests.test_integrity_invariants import assert_no_invariants_violations

pytestmark = pytest.mark.asyncio

_BREAK_GLASS_AUTHOR = "Emergency Access Admin"


async def _system_user(session: AsyncSession) -> User:
    user = await session.scalar(select(User).where(User.username == "system"))
    assert user is not None, "conftest должен создать служебного пользователя"
    return user


async def _break_glass_headers(client: AsyncClient) -> dict[str, str]:
    login = await client.post(
        "/api/auth/break-glass/login",
        json={"password": settings.BREAK_GLASS_PASSWORD},
    )
    assert login.status_code == 200, login.text
    return {"Authorization": f"Bearer {login.json()['access_token']}"}


async def test_break_glass_shopfloor_completion_defect_and_decision(
    client: AsyncClient,
    session: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Завершение с браком и последующее решение доступны и подписаны system user."""
    monkeypatch.setattr(settings, "DEV_BYPASS_AUTH", False)
    headers = await _break_glass_headers(client)
    system = await _system_user(session)
    fx = await _make_transform_setup(
        session,
        sku="BG-SHOP-181",
        planned_quantity=Decimal("100"),
        input_quantity=Decimal("100"),
    )
    await _receive_input(session, fx, quantity=Decimal("100"))
    seeded_tx_ids = set(
        (
            await session.execute(
                select(StockTransaction.id).where(StockTransaction.task_id == fx["task"].id)
            )
        ).scalars().all()
    )

    completed = await client.post(
        f"/api/shopfloor/tasks/{fx['task'].id}/complete",
        json={
            "good_quantity": "90",
            "defect_quantity": "10",
            "defect_reason": "break_glass_saw_jam",
            "comment": "completion under break-glass",
        },
        headers=headers,
    )
    assert completed.status_code == 200, completed.text
    body = completed.json()
    assert body["status"] == "in_progress"
    assert Decimal(str(body["completed_quantity"])) == Decimal("100")
    defect_id = body["defect_id"]
    assert defect_id is not None

    # Completion already creates the scrap posting and a decision-required
    # defect. The subsequent public decision is a separate legal transition.
    decision = await client.post(
        f"/api/shopfloor/defects/{defect_id}/decisions",
        json={
            "decision_type": DefectDecisionType.accept_with_deviation.value,
            "quantity": "1",
            "reason": "accepted deviation",
            "comment": "decision under break-glass",
        },
        headers=headers,
    )
    assert decision.status_code == 200, decision.text
    assert decision.json()["defect_status"] == DefectStatus.accepted_with_deviation.value

    defect = await session.get(Defect, defect_id)
    # The decision posting also carries the strict system FK.
    assert defect is not None
    assert defect.created_by == system.id
    item = await session.scalar(select(DefectItem).where(DefectItem.defect_id == defect_id))
    assert item is not None
    assert item.created_by == system.id
    decision_row = await session.get(DefectDecision, decision.json()["decision_id"])
    assert decision_row is not None
    assert decision_row.decided_by == system.id
    assert defect.stock_transaction_id is not None
    decision_tx = await session.get(StockTransaction, defect.stock_transaction_id)
    assert decision_tx is not None
    assert decision_tx.reason == Reason.COMPLETE
    assert decision_tx.created_by == system.id

    completion_txs = (
        await session.execute(
            select(StockTransaction)
            .where(
                StockTransaction.task_id == fx["task"].id,
                StockTransaction.id.not_in(seeded_tx_ids),
            )
            .order_by(StockTransaction.id)
        )
    ).scalars().all()
    assert completion_txs
    assert any(tx.reason == Reason.SCRAP for tx in completion_txs)
    assert all(tx.created_by == system.id for tx in completion_txs)
    # The ORM actor id is the strict-attribution contract here. The separate
    # #180 regression owns the emergency snapshot contract for ledger writes.
    await assert_no_invariants_violations(session, context="break-glass shopfloor")


async def test_break_glass_transfer_send_and_receive_are_attributed(
    client: AsyncClient,
    session: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Передача под break-glass создаёт принятую передачу и обе ledger-проводки."""
    # Build and complete the source task while the fixture's normal dev auth
    # is active; the actual transfer below is the strict break-glass write.
    setup = await _make_two_ghp_setup(session, sku="BG-XFER-181", qty=Decimal("10"))
    ctx = await _make_tasks_transferable(session, client, setup)
    monkeypatch.setattr(settings, "DEV_BYPASS_AUTH", False)
    system = await _system_user(session)
    headers = await _break_glass_headers(client)

    response = await client.post(
        "/api/transfers",
        json={
            "from_task_id": ctx["from_task_id"],
            "to_task_id": ctx["to_task_id"],
            "quantity": "5",
            "comment": "transfer under break-glass",
            "dimensions": None,
        },
        headers=headers,
    )
    assert response.status_code == 200, response.text
    transfer_id = response.json()["transfer_id"]
    # The ledger snapshot distinguishes emergency writes from ordinary system
    # automation; a valid FK alone is not sufficient attribution.
    transfer = await session.get(Transfer, transfer_id)
    assert transfer is not None
    assert transfer.status == TransferStatus.accepted
    assert transfer.sent_by == system.id
    assert transfer.accepted_by == system.id

    txs = (
        await session.execute(
            select(StockTransaction)
            .where(StockTransaction.transfer_id == transfer_id)
            .order_by(StockTransaction.id)
        )
    ).scalars().all()
    assert len(txs) == 2
    assert [tx.reason for tx in txs] == [Reason.TRANSFER_SEND, Reason.TRANSFER_RECEIVE]
    send_tx, receive_tx = txs
    assert (send_tx.from_location_id, send_tx.to_location_id) == (
        transfer.from_section_id,
        transfer.to_section_id,
    )
    assert (receive_tx.from_location_id, receive_tx.to_location_id) == (None, None)
    assert all(tx.created_by == system.id for tx in txs)
    await assert_no_invariants_violations(session, context="break-glass transfer")


async def test_break_glass_plan_approve_cancel_restore_records_changed_by(
    client: AsyncClient,
    session: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Approve/cancel/restore плана доступны и audit changed_by указывает system user."""
    monkeypatch.setattr(settings, "DEV_BYPASS_AUTH", False)
    system = await _system_user(session)
    setup = await _make_two_ghp_setup(session, sku="BG-PLAN-181", qty=Decimal("1"))
    plan = setup["plan"]
    position = setup["position"]
    position.status = PlanPositionStatus.draft
    position.validation_errors = []
    plan.status = ProductionPlanStatus.draft
    await session.commit()
    headers = await _break_glass_headers(client)

    approve = await client.post(
        f"/api/production-plans/{plan.id}/positions/{position.id}/approve?force=true",
        headers=headers,
    )
    assert approve.status_code == 200, approve.text
    assert approve.json()["status"] == PlanPositionStatus.approved.value

    cancel = await client.post(
        f"/api/production-plans/{plan.id}/positions/{position.id}/cancel",
        json={"reason": "cancel under break-glass"},
        headers=headers,
    )
    assert cancel.status_code == 200, cancel.text
    assert cancel.json()["status"] == PlanPositionStatus.cancelled.value

    restore = await client.post(
        f"/api/production-plans/{plan.id}/positions/{position.id}/restore",
        json={"reason": "restore under break-glass"},
        headers=headers,
    )
    assert restore.status_code == 200, restore.text
    assert restore.json()["status"] == PlanPositionStatus.approved.value

    logs = (
        await session.execute(
            select(AuditLog)
            .where(
                AuditLog.entity_type == AuditEntityType.PLAN_POSITION.value,
                AuditLog.entity_id == position.id,
                AuditLog.action.in_(
                    [AuditAction.APPROVE.value, AuditAction.CANCEL.value, AuditAction.RESTORE.value]
                ),
            )
            .order_by(AuditLog.id)
        )
    ).scalars().all()
    assert [log.action for log in logs] == [
        AuditAction.APPROVE.value,
        AuditAction.CANCEL.value,
        AuditAction.RESTORE.value,
    ]
    assert all(log.user_id == system.id for log in logs)
    assert all(log.user_name == system.full_name for log in logs)


async def test_break_glass_note_is_created_with_system_author(
    client: AsyncClient,
    session: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Note создаётся на задании и сразу виден с системным автором через API."""
    monkeypatch.setattr(settings, "DEV_BYPASS_AUTH", False)
    system = await _system_user(session)
    fx = await _make_transform_setup(session, sku="BG-NOTE-181")
    headers = await _break_glass_headers(client)

    response = await client.post(
        "/api/shopfloor/comments",
        json={
            "entity_type": "work_task",
            "entity_id": fx["task"].id,
            "body": "Заметка оператора под break-glass",
            "comment_type": "note",
        },
        headers=headers,
    )
    assert response.status_code == 201, response.text
    comment_id = response.json()["comment_id"]
    comment = await session.get(EntityComment, comment_id)
    assert comment is not None
    assert comment.author_id == system.id
    assert comment.body == "Заметка оператора под break-glass"

    public = await client.get(
        f"/api/shopfloor/entities/work_task/{fx['task'].id}/comments",
        headers=headers,
    )
    assert public.status_code == 200, public.text
    assert public.json()["comments"][0]["author_id"] == system.id


async def test_break_glass_attachment_and_link_are_created_with_system_author(
    client: AsyncClient,
    session: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Attachment и его link создаются под break-glass и читаются через API."""
    monkeypatch.setattr(settings, "DEV_BYPASS_AUTH", False)
    system = await _system_user(session)
    fx = await _make_transform_setup(session, sku="BG-ATTACH-181")
    headers = await _break_glass_headers(client)

    attachment_response = await client.post(
        "/api/shopfloor/attachments",
        json={
            "original_filename": "evidence.jpg",
            "stored_path": "break-glass/evidence.jpg",
            "size_bytes": 123,
            "content_type": "image/jpeg",
            "metadata_json": {"source": "break-glass"},
        },
        headers=headers,
    )
    assert attachment_response.status_code == 201, attachment_response.text
    attachment_id = attachment_response.json()["attachment_id"]

    link_response = await client.post(
        f"/api/shopfloor/attachments/{attachment_id}/link",
        json={
            "entity_type": "work_task",
            "entity_id": fx["task"].id,
            "caption": "Фото к заданию",
        },
        headers=headers,
    )
    assert link_response.status_code == 201, link_response.text
    link_id = link_response.json()["attachment_link_id"]

    attachment = await session.get(Attachment, attachment_id)
    link = await session.get(AttachmentLink, link_id)
    assert attachment is not None
    assert attachment.created_by == system.id
    assert link is not None
    assert link.created_by == system.id

    public = await client.get(
        f"/api/shopfloor/entities/work_task/{fx['task'].id}/attachments",
        headers=headers,
    )
    assert public.status_code == 200, public.text
    assert public.json()["attachments"][0]["original_filename"] == "evidence.jpg"
    assert public.json()["attachments"][0]["caption"] == "Фото к заданию"
