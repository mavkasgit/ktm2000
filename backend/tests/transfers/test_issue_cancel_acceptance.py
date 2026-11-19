"""Отмена выдачи против приёмки: двустороннее покрытие ADR-0071 и #349.

Правило (#282, продуктовое решение от 2026-11-03 → ADR-0071): «передача
принята» в контексте отмены — это **фактическое действие получателя / факт
исполнения**, а не технический статус, выставленный системой. Выдача
порождает передачи уже `accepted` (авто-приём), поэтому буквальная проверка
`status == accepted` запрещала бы отмену почти всегда.

#349 добавляет вторую половину правила: «принято получателем» больше не
запрещает отмену вообще, а выбирает режим. В режиме «остаток» такие
передачи остаются как есть (причина — русским текстом, без цифровых id);
полный откат возвращает и их, потому что материал можно забрать с участка
обратной проводкой.

Покрытие обязательно в обе стороны:

(а) выдача с авто-приёмкой и без действия получателя → отмена разрешена.
    Этот тест краснеет, если ``_acceptance_blocker`` свести к «status ==
    ACCEPTED»: передачи выдачи как раз все в статусе `accepted`.
(б) частичная приёмка / завершённая работа на этапе-адресате → передача
    не попадает в «остаток» и печатается причиной, но полный откат её
    забирает (проверяется в ``test_issue_cancel_modes``).

Сетап и хелперы унаследованы от ``test_issue_flow_http``: те же два склада и
правило «все плоские id захватываются до запросов».
"""
from __future__ import annotations

from decimal import Decimal

from app.models.section import Section
from app.models.transfer import Transfer, TransferStatus
from app.models.work_task import WorkTask
from app.stock.models import Reason, StockTransaction
from app.stock.services import StockCommand, StockCommandService
from sqlalchemy import func, select

from tests.test_integrity_invariants import assert_no_invariants_violations
from tests.transfers.test_issue_flow_http import (
    PREP_OPS,
    _assert_no_ids_in,
    _balance_qty,
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
    assert payload["remainder"]["can_cancel"] is True, (
        "авто-приёмка без фактического действия получателя — не основание отказа"
    )
    assert payload["full"]["can_cancel"] is True
    assert payload["remainder"]["reason"] is None
    assert len(payload["remainder"]["returns"]) == 2
    assert "Отменить нельзя" not in payload["remainder"]["summary"], payload["remainder"]["summary"]

    cancel = await client.post(
        CANCEL.format(issue_no=issue_no),
        json={"mode": "full"},
        headers=ctx["headers"],
    )
    assert cancel.status_code == 200, cancel.text
    assert len(cancel.json()["cancelled_transfers"]) == 2
    assert await _balance_qty(session, ctx["product_id"], ctx["whb_id"]) == Decimal(40)
    assert await _balance_qty(session, ctx["product_id"], ctx["raw_id"]) == Decimal(100)
    await assert_no_invariants_violations(session, context="auto-accept is not a blocker")


async def test_executed_work_is_kept_by_remainder_with_readable_reason(client, session) -> None:
    """Завершённая работа на этапе-адресате — причина остатка, без цифровых id.

    Режим «остаток» не трогает такую передачу: её материал остаётся на
    участке, склад-источник возврата не получает. Причина — имя этапа и
    количество, без id задания или участка.
    """
    ctx = await _two_warehouse_setup(session, "ACCEXEC")
    issue_no = await _issue(client, session, ctx, key="acc-exec")
    rows = await _transfers(session, issue_no)
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
    remainder = payload["remainder"]
    assert remainder["can_cancel"] is True, "вторая передача остатка отменяема"
    assert [row["transfer_id"] for row in remainder["returns"]] == [rows[1].id]
    reason = remainder["kept"][0]["reason"]
    assert "уже есть завершённая или бракованная работа" in reason, reason
    assert stage_name in reason and "5" in reason, reason
    _assert_no_ids_in(
        reason,
        [ctx["product_id"], section_id, task_id, transfer_id],
        allow=[1, 2, 3, 5, 20, 40, 60, 100],
    )

    cancel = await client.post(
        CANCEL.format(issue_no=issue_no),
        json={"mode": "remainder"},
        headers=ctx["headers"],
    )
    assert cancel.status_code == 200, cancel.text
    assert [row["transfer_id"] for row in cancel.json()["cancelled_transfers"]] == [rows[1].id]
    assert await _balance_qty(session, ctx["product_id"], ctx["whb_id"]) == Decimal(0), (
        "принятая передача не вернулась на склад"
    )
    assert await _balance_qty(session, ctx["product_id"], section_id) == Decimal(40), (
        "материал принятой передачи остался на участке"
    )
    # На принятую передачу обратных проводок нет — вернулась только вторая.
    kept_reversals = await session.scalar(
        select(func.count(StockTransaction.id)).where(
            StockTransaction.transfer_id == transfer_id,
            StockTransaction.reverses_id.is_not(None),
        )
    )
    assert kept_reversals == 0


async def test_partially_accepted_transfer_is_kept_by_remainder(client, session) -> None:
    """Частичная приёмка — тоже действие получателя, а не авто-приёмка.

    Причина обязана быть текстом-объяснением и не трогать склад: «запретили»
    в режиме «остаток» значит «оставили как есть», а не «отменили половину».
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
    remainder = payload["remainder"]
    assert [row["transfer_id"] for row in remainder["returns"]] == [row_ids[1]]
    assert remainder["kept"][0]["transfer_id"] == row_ids[0]
    reason = remainder["kept"][0]["reason"]
    assert "принята частично" in reason, reason
    assert transfer_no in reason
    assert "оставим как есть" in remainder["summary"], remainder["summary"]
    _assert_no_ids_in(
        remainder["summary"],
        [ctx["product_id"], ctx["raw_id"], ctx["whb_id"], *row_ids],
        allow=[1, 2, 3, 10, 20, 40, 60, 80, 100],
    )

    cancel = await client.post(
        CANCEL.format(issue_no=issue_no),
        json={"mode": "remainder"},
        headers=ctx["headers"],
    )
    assert cancel.status_code == 200, cancel.text
    # Отказ от принятой части не должен её отменить и вернуть её склад.
    cancelled = await session.scalar(
        select(func.count(Transfer.id)).where(
            Transfer.issue_no == issue_no, Transfer.status == TransferStatus.cancelled
        )
    )
    assert cancelled == 1, "отменена только вторая передача"
    kept = await session.get(Transfer, row_ids[0])
    assert kept.status == TransferStatus.partially_accepted
    assert await _balance_qty(session, ctx["product_id"], ctx["whb_id"]) == Decimal(0)
    assert await _balance_qty(session, ctx["product_id"], ctx["raw_id"]) == Decimal(100)


async def test_remainder_returns_only_live_transfers(client, session) -> None:
    """Отменённая передача не попадает в остаток: её уже вернули.

    Если бы предпросмотр считал все передачи подряд, уже отменённая строка
    выглядела бы «не принятой» и обещала второй возврат.
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
    remainder = payload["remainder"]
    assert remainder["returns"] == [], "в возврат идут только живые отменяемые передачи"
    assert remainder["can_cancel"] is False, "живая частично принятая передача блокирует остаток"
    assert live_no in remainder["kept"][0]["reason"], remainder["kept"][0]["reason"]
