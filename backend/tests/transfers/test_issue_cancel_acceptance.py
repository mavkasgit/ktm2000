"""Отмена выдачи целиком против приёмки: двустороннее покрытие ADR-0071.

Правило (#282, продуктовое решение от 2026-11-03 → ADR-0071): «передача
принята» в контексте запрета отмены — это **фактическое действие
получателя / факт исполнения**, а не технический статус, выставленный
системой. Выдача порождает передачи уже `accepted` (авто-приём), поэтому
буквальная проверка `status == accepted` запрещала бы полную отмену почти
всегда.

Покрытие обязательно в обе стороны:

(а) выдача с авто-приёмкой и без действия получателя → отмена **разрешена**.
    Этот тест краснеет, если ``_acceptance_blocker`` свести к «status ==
    ACCEPTED»: передачи выдачи как раз все в статусе `accepted`.
(б) частичная приёмка одной передачи / завершённая работа на этапе-адресате
    → отмена **запрещена** с русским `reason` без цифровых id, и склад не
    возвращается.

Поведение ``_acceptance_blocker`` здесь только фиксируется — оно не меняется.
Сетап и хелперы унаследованы от ``test_issue_flow_http``: те же два склада и
правило «все плоские id захватываются до запросов».
"""
from __future__ import annotations

from decimal import Decimal

from app.models.section import Section
from app.models.transfer import Transfer, TransferStatus
from app.models.work_task import WorkTask
from app.stock.models import Reason
from app.stock.services import StockCommand, StockCommandService
from sqlalchemy import func, select

from tests.test_integrity_invariants import assert_no_invariants_violations
from tests.transfers.test_issue_flow_http import (
    PREP_OPS,
    _assert_no_ids_in,
    _balance_qty,
    _sends,
    _take,
    _transfers,
    _two_warehouse_setup,
)

CANCEL = "/api/transfers/issues/{issue_no}/cancel"
PREVIEW = CANCEL + "-preview"


async def _issue(client, session, ctx, *, key: str, quantity: str = "60") -> str:
    body = await _take(
        client, ctx["headers"],
        position_ids=[ctx["position_id"]],
        release_quantity=quantity,
        issue={"shortage_strategy": "partial", "idempotency_key": key},
    )
    result = body["results"][0]
    assert result["status"] == "success", result
    return result["issue"]["issue_no"]


async def _cancel_preview(client, ctx, issue_no: str) -> dict:
    resp = await client.get(PREVIEW.format(issue_no=issue_no), headers=ctx["headers"])
    assert resp.status_code == 200, resp.text
    return resp.json()


async def test_auto_acceptance_alone_does_not_block_full_cancellation(client, session) -> None:
    """Авто-приёмка не блокатор: передача `accepted` руками системы (#282).

    Красный ход по ADR-0071: если ``_acceptance_blocker`` начать с
    ``if transfer.status == TransferStatus.accepted``, отменять станет
    нечего — все передачи выдачи как раз `accepted` сразу после создания.
    """
    ctx = await _two_warehouse_setup(session, "ACC-AUTO")
    issue_no = await _issue(client, session, ctx, key="acc-auto")

    rows = await _transfers(session, issue_no)
    assert len(rows) == 2
    assert all(t.status == TransferStatus.accepted for t in rows), (
        "премиса: приёмка выставлена системой, действия получателя не было"
    )

    payload = await _cancel_preview(client, ctx, issue_no)
    assert payload["can_cancel"] is True, (
        "авто-приёмка без фактического действия получателя — не основание отказа"
    )
    assert payload["reason"] is None
    assert len(payload["returns"]) == 2
    assert "Отменить нельзя" not in payload["summary"], payload["summary"]

    cancel = await client.post(CANCEL.format(issue_no=issue_no), headers=ctx["headers"])
    assert cancel.status_code == 200, cancel.text
    assert len(cancel.json()["cancelled_transfers"]) == 2
    assert await _balance_qty(session, ctx["product_id"], ctx["whb_id"]) == Decimal(40)
    assert await _balance_qty(session, ctx["product_id"], ctx["raw_id"]) == Decimal(100)
    await assert_no_invariants_violations(session, context="auto-accept is not a blocker")


async def test_partially_accepted_transfer_blocks_full_cancellation(client, session) -> None:
    """Частичная приёмка одной передачи — основание отказать всей выдаче.

    Отказ обязан быть текстом-причиной (в `reason` и в ответе 400) и не
    должен трогать склад: «запретили» не значит «отменили половину».
    """
    ctx = await _two_warehouse_setup(session, "ACCPART")
    issue_no = await _issue(client, session, ctx, key="acc-part")
    rows = await _transfers(session, issue_no)
    half = rows[0]
    transfer_no = half.transfer_no  # захватываем до commit: коммит экспайрит объекты
    row_ids = [t.id for t in rows]
    # Фактическое действие получателя: материал приняли не целиком.
    half.status = TransferStatus.partially_accepted
    half.accepted_quantity = Decimal(10)
    await session.commit()

    payload = await _cancel_preview(client, ctx, issue_no)
    assert payload["can_cancel"] is False
    assert "принята частично" in payload["reason"], payload["reason"]
    assert transfer_no in payload["reason"]
    assert "Отменить нельзя" in payload["summary"], payload["summary"]
    _assert_no_ids_in(
        payload["summary"],
        [ctx["product_id"], ctx["raw_id"], ctx["whb_id"], *row_ids],
        allow=[1, 2, 3, 10, 20, 40, 60, 80, 100],
    )

    cancel = await client.post(CANCEL.format(issue_no=issue_no), headers=ctx["headers"])
    assert cancel.status_code == 400, cancel.text
    assert "принята частично" in cancel.json()["detail"]
    assert await _balance_qty(session, ctx["product_id"], ctx["whb_id"]) == Decimal(0), (
        "отказ не должен возвращать склад"
    )
    assert await _balance_qty(session, ctx["product_id"], ctx["raw_id"]) == Decimal(80)
    # Отказ не должен отменить ни одну передачу: считаем плоским запросом,
    # чтобы не упираться в экспаеринг общей сессии после rollback роута.
    cancelled = await session.scalar(
        select(func.count(Transfer.id)).where(
            Transfer.issue_no == issue_no, Transfer.status == TransferStatus.cancelled
        )
    )
    assert cancelled == 0, "отказ не должен отменять передачи"


async def test_executed_work_on_intake_stage_blocks_full_cancellation(client, session) -> None:
    """Отработанная работа на этапе-адресате — возврат породил бы минус.

    Второй блокатор из ADR-0071: на приёмном этапе есть `completed_quantity`.
    Причина — имя этапа и количество, без цифровых id задания или участка.
    """
    ctx = await _two_warehouse_setup(session, "ACCEXEC")
    issue_no = await _issue(client, session, ctx, key="acc-exec")
    rows = await _transfers(session, issue_no)
    # Порядок вычерпывания: первая передача идёт на этап 3 (приёмка подготовки).
    intake = rows[0]
    task = await session.get(WorkTask, intake.to_task_id)
    section_id = task.section_id
    task_id = task.id
    transfer_id = intake.id
    stage_name = (await session.get(Section, section_id)).name
    # Факт исполнения получателем: часть материала на этапе уже завершена.
    await StockCommandService().record(
        session,
        StockCommand(
            product_id=ctx["product_id"],
            from_location_id=section_id,
            to_location_id=section_id,
            quantity=Decimal(5),
            reason=Reason.COMPLETE,
            task_id=task_id,
            completed_operations=PREP_OPS,
            source_ref="test_seed",
            created_by=ctx["user_id"],
        ),
    )
    await session.commit()

    payload = await _cancel_preview(client, ctx, issue_no)
    assert payload["can_cancel"] is False, "завершённая работа — основание отказа"
    assert "уже есть завершённая или бракованная работа" in payload["reason"], payload["reason"]
    assert stage_name in payload["reason"] and "5" in payload["reason"], payload["reason"]
    _assert_no_ids_in(
        payload["reason"],
        [ctx["product_id"], section_id, task_id, transfer_id],
        allow=[1, 2, 3, 5, 20, 40, 60, 100],
    )

    cancel = await client.post(CANCEL.format(issue_no=issue_no), headers=ctx["headers"])
    assert cancel.status_code == 400, cancel.text
    assert "не отменить" in cancel.json()["detail"], cancel.text
    assert len(await _sends(session)) == 2, "отказ не дописывает проводки"


async def test_blocker_counts_only_live_transfers(client, session) -> None:
    """Блокатор и возврат идут по живым передачам: отменённая не блокирует.

    Если бы ``preview_issue_cancellation`` смотрел все передачи выдачи подряд,
    уже отменённая передача (`cancelled`, а не `accepted`) молча прошла бы как
    «не принята», а возврат живого упал бы на готовую компенсацию (#282).
    """
    ctx = await _two_warehouse_setup(session, "ACCMIX")
    issue_no = await _issue(client, session, ctx, key="acc-mix")
    rows = await _transfers(session, issue_no)
    assert len(rows) == 2
    live_no = rows[0].transfer_no
    for transfer in rows:
        transfer.status = TransferStatus.cancelled
    rows[0].status = TransferStatus.partially_accepted
    await session.commit()

    payload = await _cancel_preview(client, ctx, issue_no)
    assert len(payload["returns"]) == 1, "в возврат идут только живые передачи"
    assert payload["returns"][0]["transfer_no"] == live_no
    assert payload["can_cancel"] is False, "живая частично принятая передача блокирует"
    assert live_no in payload["reason"], payload["reason"]
