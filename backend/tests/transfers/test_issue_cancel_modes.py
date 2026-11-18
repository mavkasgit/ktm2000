"""Отмена выдачи в двух режимах (#349).

Решение владельца: оператор выбирает явно, что делать с принятой частью.

* ``remainder`` — отменяется только непринятая часть. Передачи, по которым
  получатель уже что-то сделал (частичная приёмка или факт исполнения),
  остаются как есть: их проводки не компенсируются, материал остаётся на
  участке. Это проверяется не только статусом, но и ledger'ом: у оставленной
  передачи нет ни одной компенсирующей проводки.
* ``full`` — полный откат: отменяется вся выдача, включая принятую часть.
  Обратные проводки пишет тот же ``ReversalService``, что и приёмка
  (ADR-0019), поэтому склады-источники возвращаются к остаткам до выдачи, а
  S1–S6 остаются зелёными. Запрещающие статусы (``amended``/``rejected``)
  отказывают до первой проводки — выдача отменяется целиком или никак.

Повтор идемпотентен: с тем же ``idempotency_key`` возвращается записанный
исход операции, без ключа повтор при отсутствии живых передач тоже честно
отвечает исходом. Склад при этом не двигается ни на одну проводку.

Аудит обязан быть в обоих режимах: на каждую отменённую передачу (режим,
номер выдачи, ключ, ``reversed_tx_ids``) и на операцию целиком.
"""
from __future__ import annotations

from decimal import Decimal

from app.core.security import create_access_token
from app.models.audit_log import AuditLog
from app.models.transfer import Transfer, TransferStatus
from app.models.user import User, UserRole
from app.models.work_task import WorkTask
from app.stock.models import Reason, StockTransaction
from app.stock.services import StockCommand, StockCommandService
from sqlalchemy import func, select

from tests.test_integrity_invariants import (
    assert_no_invariants_violations,
    assert_no_stock_ledger_invariants_violations,
)
from tests.transfers.test_issue_flow_http import (
    PREP_OPS,
    _balance_qty,
    _take,
    _transfers,
    _two_warehouse_setup,
)

CANCEL = "/api/transfers/issues/{issue_no}/cancel"
PREVIEW = CANCEL + "-preview"


async def _issue(client, ctx, *, key: str, quantity: str = "60") -> str:
    body = await _take(
        client,
        ctx["headers"],
        position_ids=[ctx["position_id"]],
        release_quantity=quantity,
        issue={"shortage_strategy": "partial", "idempotency_key": key},
    )
    result = body["results"][0]
    assert result["status"] == "success", result
    return result["issue"]["issue_no"]


async def _cancel(client, ctx, issue_no: str, *, mode: str, key: str | None = None):
    payload = {"mode": mode}
    if key is not None:
        payload["idempotency_key"] = key
    return await client.post(CANCEL.format(issue_no=issue_no), json=payload, headers=ctx["headers"])


async def _preview(client, ctx, issue_no: str) -> dict:
    resp = await client.get(PREVIEW.format(issue_no=issue_no), headers=ctx["headers"])
    assert resp.status_code == 200, resp.text
    return resp.json()


async def _tx_count(session) -> int:
    return int(await session.scalar(select(func.count(StockTransaction.id))) or 0)


async def _record_completed_work(session, *, transfer: Transfer, product_id: int, actor_id: int) -> None:
    """Факт исполнения получателя: часть материала уже завершена на этапе."""
    task = await session.get(WorkTask, transfer.to_task_id)
    assert task is not None
    await StockCommandService().record(
        session,
        StockCommand(
            product_id=product_id,
            from_location_id=task.section_id,
            to_location_id=task.section_id,
            quantity=Decimal(5),
            reason=Reason.COMPLETE,
            task_id=task.id,
            completed_operations=PREP_OPS,
            source_ref="test_issue_cancel_modes",
            created_by=actor_id,
        ),
    )
    await session.commit()


async def test_preview_explains_both_modes(client, session) -> None:
    """Предпросмотр отдаёт оба сценария: остаток и полный откат.

    «Принято получателем» — это факты исполнения, а не авто-приёмка (#349,
    ADR-0071): у оставленной передачи видно и количество, и причину.
    """
    ctx = await _two_warehouse_setup(session, "ONCEPV")
    issue_no = await _issue(client, ctx, key="oncepv-1")
    rows = await _transfers(session, issue_no)
    await _record_completed_work(
        session, transfer=rows[0], product_id=ctx["product_id"], actor_id=ctx["user_id"]
    )

    preview = await _preview(client, ctx, issue_no)
    assert preview["issue_no"] == issue_no
    assert len(preview["transfers"]) == 2

    remainder = preview["remainder"]
    assert remainder["can_cancel"] is True, "вторая передача остатка отменяема"
    assert [row["transfer_id"] for row in remainder["returns"]] == [rows[1].id]
    assert len(remainder["kept"]) == 1 and remainder["kept"][0]["transfer_id"] == rows[0].id
    assert "завершённая или бракованная работа" in remainder["kept"][0]["reason"]
    assert "оставим как есть" in remainder["summary"], remainder["summary"]

    full = preview["full"]
    assert full["can_cancel"] is True
    assert {row["transfer_id"] for row in full["returns"]} == {rows[0].id, rows[1].id}
    assert full["accepted_quantity"] == "5", "в предупреждении — факт исполнения получателя"
    assert "включая принятое получателем: 5 шт." in full["summary"], full["summary"]


async def test_remainder_cancels_only_remainder_and_leaves_accepted_untouched(client, session) -> None:
    """Остаток отменяется без движения принятого.

    Половина выдачи уже отработана получателем. Режим ``remainder`` обязан
    вернуть только вторую передачу: у оставленной не появляется ни одной
    компенсирующей проводки, её материал остаётся на участке, а склад,
    с которого она пришла, не получает возврата.
    """
    ctx = await _two_warehouse_setup(session, "ONCEREM")
    issue_no = await _issue(client, ctx, key="oncerem-1")
    rows = await _transfers(session, issue_no)
    kept, returned = rows[0], rows[1]
    kept_task = await session.get(WorkTask, kept.to_task_id)
    assert kept_task is not None
    kept_stage_id = kept_task.section_id
    kept_id, returned_id = kept.id, returned.id
    await _record_completed_work(
        session, transfer=kept, product_id=ctx["product_id"], actor_id=ctx["user_id"]
    )
    before_tx = await _tx_count(session)

    resp = await _cancel(client, ctx, issue_no, mode="remainder")
    assert resp.status_code == 200, resp.text
    payload = resp.json()
    assert payload["mode"] == "remainder"
    assert payload["idempotent_replay"] is False
    assert [row["transfer_id"] for row in payload["cancelled_transfers"]] == [returned_id]
    assert [row["transfer_id"] for row in payload["kept_transfers"]] == [kept_id]
    assert "завершённая или бракованная работа" in payload["kept_transfers"][0]["reason"]

    transfers = {t.id: t for t in await _transfers(session, issue_no)}
    assert transfers[returned_id].status == TransferStatus.cancelled
    assert transfers[kept_id].status == TransferStatus.accepted, "принятое остаётся как есть"

    # Принятая передача не получила ни одной обратной проводки.
    kept_reversals = list(
        (
            await session.execute(
                select(StockTransaction).where(
                    StockTransaction.transfer_id == kept_id,
                    StockTransaction.reverses_id.is_not(None),
                )
            )
        ).scalars().all()
    )
    assert kept_reversals == [], "принятую передачу режим «остаток» не трогает"

    assert await _balance_qty(session, ctx["product_id"], ctx["whb_id"]) == Decimal(0), (
        "склад принятой передачи не возвращается"
    )
    assert await _balance_qty(session, ctx["product_id"], kept_stage_id) == Decimal(40), (
        "материал принятой передачи остался на участке"
    )
    assert await _balance_qty(session, ctx["product_id"], ctx["raw_id"]) == Decimal(100), (
        "остаток второй передачи вернулся на склад"
    )
    after_tx = await _tx_count(session)
    assert after_tx > before_tx, "возврат остатка оформлен проводками"
    await assert_no_invariants_violations(session, context="remainder cancel")
    await assert_no_stock_ledger_invariants_violations(session, context="remainder cancel")


async def test_full_rollback_returns_everything_including_accepted(client, session) -> None:
    """Полный откат отменяет и принятую часть, склады сходятся.

    Частично принятая передача в режиме ``remainder`` осталась бы, а в
    ``full`` компенсируется вместе с остальными: склад-источник получает
    весь материал обратно, участок освобождается, S6 не краснеет на статусе.
    """
    ctx = await _two_warehouse_setup(session, "ONCEFULL")
    issue_no = await _issue(client, ctx, key="oncefull-1")
    rows = await _transfers(session, issue_no)
    accepted = rows[0]
    accepted.status = TransferStatus.partially_accepted
    accepted.accepted_quantity = Decimal(10)
    await session.commit()

    resp = await _cancel(client, ctx, issue_no, mode="full")
    assert resp.status_code == 200, resp.text
    payload = resp.json()
    assert payload["mode"] == "full"
    assert {row["transfer_id"] for row in payload["cancelled_transfers"]} == {t.id for t in rows}
    assert payload["kept_transfers"] == []
    assert payload["reversed_tx_ids"], "полный откат обязан вернуть id обратных проводок"

    for transfer in await _transfers(session, issue_no):
        assert transfer.status == TransferStatus.cancelled, transfer.transfer_no

    assert await _balance_qty(session, ctx["product_id"], ctx["whb_id"]) == Decimal(40)
    assert await _balance_qty(session, ctx["product_id"], ctx["raw_id"]) == Decimal(100)

    reversals = list(
        (
            await session.execute(
                select(StockTransaction).where(StockTransaction.reverses_id.is_not(None))
            )
        ).scalars().all()
    )
    assert {row.transfer_id for row in reversals} == {t.id for t in rows}, (
        "обратные проводки обязаны принадлежать отменённым передачам"
    )
    await assert_no_invariants_violations(session, context="full rollback")
    await assert_no_stock_ledger_invariants_violations(session, context="full rollback")


async def test_repeat_with_operation_key_is_idempotent(client, session) -> None:
    """Повтор с тем же ключом не задваивает движения склада."""
    ctx = await _two_warehouse_setup(session, "ONCEIDEM")
    issue_no = await _issue(client, ctx, key="onceidem-1")

    first = await _cancel(client, ctx, issue_no, mode="full", key="cancel-once")
    assert first.status_code == 200, first.text
    after_first = await _tx_count(session)
    balances = (
        await _balance_qty(session, ctx["product_id"], ctx["whb_id"]),
        await _balance_qty(session, ctx["product_id"], ctx["raw_id"]),
    )

    second = await _cancel(client, ctx, issue_no, mode="full", key="cancel-once")
    assert second.status_code == 200, second.text
    replay = second.json()
    assert replay["idempotent_replay"] is True
    assert replay["mode"] == "full"
    assert len(replay["cancelled_transfers"]) == 2
    assert await _tx_count(session) == after_first, "повтор не добавляет проводок"
    assert (
        await _balance_qty(session, ctx["product_id"], ctx["whb_id"]),
        await _balance_qty(session, ctx["product_id"], ctx["raw_id"]),
    ) == balances


async def test_repeat_without_key_is_idempotent_when_nothing_live(client, session) -> None:
    """Повтор без ключа при отсутствии живых передач — исход, а не второй возврат."""
    ctx = await _two_warehouse_setup(session, "ONCEREP")
    issue_no = await _issue(client, ctx, key="oncerep-1")

    assert (await _cancel(client, ctx, issue_no, mode="full")).status_code == 200
    after_first = await _tx_count(session)

    again = await _cancel(client, ctx, issue_no, mode="full")
    assert again.status_code == 200, again.text
    assert again.json()["idempotent_replay"] is True
    assert await _tx_count(session) == after_first


async def test_full_rollback_refuses_amended_transfer_without_movements(client, session) -> None:
    """Запрещающий статус — отказ до первой проводки, без полу-отмены."""
    ctx = await _two_warehouse_setup(session, "ONCEBLK")
    issue_no = await _issue(client, ctx, key="onceblk-1")
    rows = await _transfers(session, issue_no)
    rows[0].status = TransferStatus.amended
    await session.commit()
    before = await _tx_count(session)

    preview = await _preview(client, ctx, issue_no)
    assert preview["full"]["can_cancel"] is False
    assert "скорректирована" in preview["full"]["reason"], preview["full"]["reason"]

    resp = await _cancel(client, ctx, issue_no, mode="full")
    assert resp.status_code == 400, resp.text
    assert "скорректирована" in resp.json()["detail"]
    assert await _tx_count(session) == before, "отказ не пишет проводок"
    live = [t for t in await _transfers(session, issue_no) if t.id != rows[0].id]
    assert all(t.status != TransferStatus.cancelled for t in live), "половина выдачи не отменена"


async def test_audit_records_mode_and_rollback_in_both_modes(client, session) -> None:
    """Аудит: кто, когда, выдача, режим и что откатили — в обоих режимах."""
    remainder_ctx = await _two_warehouse_setup(session, "ONCEAUDR")
    full_ctx = await _two_warehouse_setup(session, "ONCEAUDF")
    remainder_issue = await _issue(client, remainder_ctx, key="onceaud-rem")
    full_issue = await _issue(client, full_ctx, key="onceaud-full")

    assert (
        await _cancel(client, remainder_ctx, remainder_issue, mode="remainder")
    ).status_code == 200
    assert (await _cancel(client, full_ctx, full_issue, mode="full")).status_code == 200

    rows = list(
        (
            await session.execute(
                select(AuditLog).order_by(AuditLog.id)
            )
        ).scalars().all()
    )
    operation_rows = {
        row.changes["issue_no"]: row
        for row in rows
        if (row.changes or {}).get("operation") == "issue_cancel"
    }
    assert set(operation_rows) == {remainder_issue, full_issue}

    for issue_no, mode, ctx in (
        (remainder_issue, "remainder", remainder_ctx),
        (full_issue, "full", full_ctx),
    ):
        row = operation_rows[issue_no]
        assert row.action == "cancel" and row.entity_type == "transfer"
        assert row.user_id == ctx["user_id"], "аудит знает, кто отменил"
        assert row.created_at is not None, "аудит знает, когда отменил"
        changes = row.changes
        assert changes["mode"] == mode
        assert changes["cancelled_transfers"], "аудит перечисляет отменённые передачи"
        assert changes["reversed_tx_ids"], "аудит перечисляет обратные проводки"

    # На каждую отменённую передачу — своя запись с режимом и номером выдачи.
    transfer_rows = [
        row
        for row in rows
        if row.entity_type == "transfer"
        and (row.changes or {}).get("mode") is not None
        and (row.changes or {}).get("operation") != "issue_cancel"
    ]
    modes = {(row.changes or {}).get("mode") for row in transfer_rows}
    assert modes == {"remainder", "full"}
    assert all(row.changes.get("issue_no") for row in transfer_rows)


async def test_viewer_cannot_cancel_issue(client, session) -> None:
    """Права — как у остальных операций с передачами: viewer получает 403."""
    ctx = await _two_warehouse_setup(session, "ONCE403")
    issue_no = await _issue(client, ctx, key="once403-1")

    viewer = User(
        email="once403-viewer@local",
        full_name="Once Viewer",
        role=UserRole.viewer,
        is_active=True,
    )
    session.add(viewer)
    await session.commit()
    headers = {"Authorization": f"Bearer {create_access_token(subject=viewer.email)}"}

    for mode in ("remainder", "full"):
        resp = await client.post(
            CANCEL.format(issue_no=issue_no), json={"mode": mode}, headers=headers
        )
        assert resp.status_code == 403, (mode, resp.status_code, resp.text)

    assert all(
        t.status != TransferStatus.cancelled for t in await _transfers(session, issue_no)
    ), "403 не отменяет ни одной передачи"
