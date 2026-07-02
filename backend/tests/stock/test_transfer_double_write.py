"""Тесты двойной записи Transfer → Stock Ledger (Этап 2 рефакторинга).

Покрывают:
1. ``transfer_send`` создаёт **одну** ``StockTransaction`` с честной
   ledger-геометрией ``from=from_section → to=to_section``, reason
   ``TRANSFER_SEND``, ``task_id=from_task`` (одна проводка двигает обе
   локации сразу, без split-геометрии).
2. ``StockBalance`` обновляется по результату одной транзакции.
3. Идемпотентность ``transfer_send`` (повтор не плодит дублей).
4. ``cancel_transfer`` создаёт **одну** компенсационную
   ``StockTransaction`` с перевёрнутыми локациями и
   ``compensates_tx_id`` → исходная (append-only).
5. Идемпотентность ``cancel_transfer`` через status guard.
6. ``correct_transfer`` синхронно меняет quantity активной
   ``StockTransaction`` in-place (контролируемое mutable-исключение).
7. ``auto_create_transfer_after_complete`` тоже пишет в Stock Ledger
   (одну tx с ``is_post_factum=True``).
8. Полный цикл e2e: complete → transfer_send → correct → cancel.

Использует хелперы из ``test_integrity_invariants.py``
(``_make_user``, ``_auth_headers``, ``_make_two_ghp_route``,
``_release_via_take_to_work``) и ``test_transfers_module.py``
(``_issue_via_db``). Хелперы assert из
``test_integrity_invariants.assert_no_*_invariants_violations`` гарантируют,
что новый Stock Ledger сходится со старыми projections на каждом шаге.
"""
from __future__ import annotations

from decimal import Decimal

import pytest
from sqlalchemy import select

from app.models.movement import Movement, MovementType
from app.models.work_task import WorkTask
from app.stock.models import QualityState, Reason, StockBalance, StockTransaction
from app.transfers.services import (
    auto_create_transfer_after_complete,
    cancel_transfer,
    correct_transfer,
    transfer_send,
)
from tests.test_integrity_invariants import (
    _auth_headers,
    _make_two_ghp_route,
    _make_user,
    _release_via_take_to_work,
    assert_no_invariants_violations,
    assert_no_stock_ledger_invariants_violations,
)
from tests.test_transfers_module import _issue_via_db  # noqa: F401 — re-exported helper kept for parity with other transfer tests


# ─── helpers ─────────────────────────────────────────────────────────────────


async def _stock_txs_for_transfer(session, transfer_id: int) -> list[StockTransaction]:
    """Все StockTransactions для transfer в порядке создания."""
    return (
        await session.execute(
            select(StockTransaction)
            .where(StockTransaction.transfer_id == transfer_id)
            .order_by(StockTransaction.id.asc())
        )
    ).scalars().all()


async def _balance_qty(
    session,
    product_id: int,
    location_id: int,
    quality_state: QualityState = QualityState.good,
) -> Decimal:
    """Возвращает текущий StockBalance (0 если строки нет)."""
    row = await session.execute(
        select(StockBalance).where(
            StockBalance.product_id == product_id,
            StockBalance.location_id == location_id,
            StockBalance.quality_state == quality_state,
        )
    )
    bal = row.scalar_one_or_none()
    return bal.balance_qty if bal else Decimal("0")


async def _issue_complete_first_task(
    client, session, user, task_id: int, qty: Decimal, *, complete_key: str
) -> int:
    """Issue + complete первую задачу через БД + API. Возвращает task_id."""
    from app.services.shopfloor.cache import (
        _refresh_section_plan_line_cache,
        _refresh_task_cache,
    )

    task = await session.get(WorkTask, task_id)
    m = Movement(
        product_id=task.product_id,
        task_id=task.id,
        section_plan_line_id=task.section_plan_line_id,
        from_section_id=task.section_id,
        to_section_id=task.section_id,
        movement_type=MovementType.issue_to_work,
        quantity=qty,
        created_by=user.id,
    )
    session.add(m)
    await session.flush()
    await _refresh_task_cache(session, task_id)
    await _refresh_section_plan_line_cache(session, task.section_plan_line_id)
    await session.flush()
    resp = await client.post(
        f"/api/shopfloor/tasks/{task_id}/complete",
        json={
            "good_quantity": str(qty),
            "defect_quantity": "0",
            "idempotency_key": complete_key,
        },
        headers=_auth_headers(user),
    )
    assert resp.status_code == 200, resp.text
    return task_id


# ─── tests: transfer_send → 1 StockTransaction ──────────────────────────────


@pytest.mark.asyncio
async def test_transfer_send_creates_one_stock_transaction(client, session) -> None:
    """После ``transfer_send`` ровно 1 ``StockTransaction`` с честной
    ledger-геометрией: ``from=from_section → to=to_section``, reason
    ``TRANSFER_SEND``, ``task_id=from_task``. ``TRANSFER_RECEIVE`` в
    ``transfer_send`` больше не пишется (reason оставлен в enum для
    будущего partial-accept, см. PLAN_stock_ledger.md → Этап 7).
    """
    user = await _make_user(session, "tx-dw-send@test.local")
    fx = await _make_two_ghp_route(session, sku="TX-DW-SEND", qty=Decimal("10"))
    await _release_via_take_to_work(client, fx["position"].id)

    tasks = (await session.execute(
        select(WorkTask).order_by(WorkTask.id.asc())
    )).scalars().all()
    assert len(tasks) == 2
    src_task, dst_task = tasks[0], tasks[1]
    src_section, dst_section = fx["sections"][0], fx["sections"][1]

    await _issue_complete_first_task(
        client, session, user, src_task.id, Decimal("10"),
        complete_key="tx-dw-send:complete",
    )

    send = await client.post(
        "/api/transfers",
        json={
            "from_task_id": src_task.id,
            "to_task_id": dst_task.id,
            "quantity": "10",
            "idempotency_key": "tx-dw-send:send",
        },
        headers=_auth_headers(user),
    )
    assert send.status_code == 200, send.text
    transfer_id = send.json()["transfer_id"]

    stock_txs = await _stock_txs_for_transfer(session, transfer_id)
    assert len(stock_txs) == 1, f"Expected 1 StockTransaction, got {len(stock_txs)}"

    tx = stock_txs[0]
    assert tx.reason == Reason.transfer_send, f"reason={tx.reason!r}, expected transfer_send"
    assert tx.from_location_id == src_section.id
    assert tx.to_location_id == dst_section.id
    assert tx.quantity == Decimal("10")
    assert tx.compensates_tx_id is None
    assert tx.task_id == src_task.id
    assert tx.transfer_id == transfer_id

    # Нет ни одной tx с reason=transfer_receive — split-геометрия отключена.
    receive_txs = [t for t in stock_txs if t.reason == Reason.transfer_receive]
    assert receive_txs == [], "TRANSFER_RECEIVE must not be written by transfer_send"

    await assert_no_stock_ledger_invariants_violations(session, context="after-send")


@pytest.mark.asyncio
async def test_transfer_send_stock_balance_reflects_movement(client, session) -> None:
    """После transfer_send StockBalance на from_section = -qty, на
    to_section = +qty. Если баланс 0, строка удаляется
    (ck_stock_balances_nonzero).
    """
    user = await _make_user(session, "tx-dw-bal@test.local")
    fx = await _make_two_ghp_route(session, sku="TX-DW-BAL", qty=Decimal("7"))
    await _release_via_take_to_work(client, fx["position"].id)
    tasks = (await session.execute(
        select(WorkTask).order_by(WorkTask.id.asc())
    )).scalars().all()
    src_task, dst_task = tasks[0], tasks[1]
    src_section, dst_section = fx["sections"][0], fx["sections"][1]
    product = fx["product"]

    await _issue_complete_first_task(
        client, session, user, src_task.id, Decimal("7"),
        complete_key="tx-dw-bal:complete",
    )
    send = await client.post(
        "/api/transfers",
        json={
            "from_task_id": src_task.id,
            "to_task_id": dst_task.id,
            "quantity": "7",
            "idempotency_key": "tx-dw-bal:send",
        },
        headers=_auth_headers(user),
    )
    assert send.status_code == 200, send.text

    # Единственная StockTransaction с from=src → to=dst двигает обе локации.
    assert (await _balance_qty(session, product.id, src_section.id)) == Decimal("-7")
    assert (await _balance_qty(session, product.id, dst_section.id)) == Decimal("7")

    # S1 (баланс = SUM(in) − SUM(out) per location) должен сходиться.
    await assert_no_stock_ledger_invariants_violations(session, context="after-send")


@pytest.mark.asyncio
async def test_transfer_send_idempotency_no_duplicate_stock_tx(client, session) -> None:
    """Повторный ``POST /api/transfers`` с тем же idempotency_key не
    плодит дублей StockTransaction (всё ещё 1, не 2).
    """
    user = await _make_user(session, "tx-dw-idem@test.local")
    fx = await _make_two_ghp_route(session, sku="TX-DW-IDEM", qty=Decimal("5"))
    await _release_via_take_to_work(client, fx["position"].id)
    tasks = (await session.execute(
        select(WorkTask).order_by(WorkTask.id.asc())
    )).scalars().all()
    src_task, dst_task = tasks[0], tasks[1]

    await _issue_complete_first_task(
        client, session, user, src_task.id, Decimal("5"),
        complete_key="tx-dw-idem:complete",
    )
    body = {
        "from_task_id": src_task.id,
        "to_task_id": dst_task.id,
        "quantity": "5",
        "idempotency_key": "tx-dw-idem:send",
    }
    first = await client.post("/api/transfers", json=body, headers=_auth_headers(user))
    assert first.status_code == 200, first.text
    transfer_id = first.json()["transfer_id"]

    second = await client.post("/api/transfers", json=body, headers=_auth_headers(user))
    assert second.status_code == 200, second.text
    assert second.json().get("idempotent_replay") is True
    assert second.json()["transfer_id"] == transfer_id

    stock_txs = await _stock_txs_for_transfer(session, transfer_id)
    assert len(stock_txs) == 1, (
        f"Replay must not create duplicate StockTransactions; got {len(stock_txs)}"
    )
    assert stock_txs[0].reason == Reason.transfer_send
    assert stock_txs[0].quantity == Decimal("5")

    await assert_no_stock_ledger_invariants_violations(session, context="after-replay")


# ─── tests: cancel_transfer → 1 compensating StockTransaction ───────────────


@pytest.mark.asyncio
async def test_cancel_transfer_creates_compensating_stock_transactions(
    client, session
) -> None:
    """``cancel_transfer`` пишет **одну** компенсационную StockTransaction
    с перевёрнутыми локациями (``from=to_section, to=from_section``) и
    ``compensates_tx_id`` → исходная. Суммарный баланс по transfer
    возвращается к 0 → строка StockBalance удаляется
    (ck_stock_balances_nonzero). Append-only: исходная tx остаётся в
    ledger, рядом с ней появляется встречная.
    """
    user = await _make_user(session, "tx-dw-cancel@test.local")
    fx = await _make_two_ghp_route(session, sku="TX-DW-CNCL", qty=Decimal("8"))
    await _release_via_take_to_work(client, fx["position"].id)
    tasks = (await session.execute(
        select(WorkTask).order_by(WorkTask.id.asc())
    )).scalars().all()
    src_task, dst_task = tasks[0], tasks[1]
    src_section, dst_section = fx["sections"][0], fx["sections"][1]
    product = fx["product"]

    await _issue_complete_first_task(
        client, session, user, src_task.id, Decimal("8"),
        complete_key="tx-dw-cncl:complete",
    )
    send = await client.post(
        "/api/transfers",
        json={
            "from_task_id": src_task.id,
            "to_task_id": dst_task.id,
            "quantity": "8",
            "idempotency_key": "tx-dw-cncl:send",
        },
        headers=_auth_headers(user),
    )
    assert send.status_code == 200, send.text
    transfer_id = send.json()["transfer_id"]

    cancel = await client.post(
        f"/api/transfers/{transfer_id}/cancel", headers=_auth_headers(user)
    )
    assert cancel.status_code == 200, cancel.text
    assert cancel.json()["status"] == "cancelled"

    all_txs = await _stock_txs_for_transfer(session, transfer_id)
    originals = [t for t in all_txs if t.compensates_tx_id is None]
    comps = [t for t in all_txs if t.compensates_tx_id is not None]
    assert len(originals) == 1, f"Expected 1 original StockTransaction, got {len(originals)}"
    assert len(comps) == 1, f"Expected 1 compensating StockTransaction, got {len(comps)}"
    assert len(all_txs) == 2, f"Expected 2 total (1 orig + 1 comp), got {len(all_txs)}"

    orig = originals[0]
    comp = comps[0]

    # Исходная tx: честная геометрия from=src → to=dst, reason=TRANSFER_SEND.
    assert orig.reason == Reason.transfer_send
    assert orig.from_location_id == src_section.id
    assert orig.to_location_id == dst_section.id
    assert orig.quantity == Decimal("8")
    assert orig.compensates_tx_id is None

    # Компенсация: перевёрнутые локации, reason наследуется от исходной,
    # compensates_tx_id → исходная.
    assert comp.reason == Reason.transfer_send
    assert comp.from_location_id == dst_section.id, (
        f"comp.from_location_id={comp.from_location_id} should be dst_section.id={dst_section.id}"
    )
    assert comp.to_location_id == src_section.id, (
        f"comp.to_location_id={comp.to_location_id} should be src_section.id={src_section.id}"
    )
    assert comp.quantity == orig.quantity
    assert comp.compensates_tx_id == orig.id

    # Балансы вернулись к 0 → StockBalance строки удалены
    assert (await _balance_qty(session, product.id, src_section.id)) == Decimal("0")
    assert (await _balance_qty(session, product.id, dst_section.id)) == Decimal("0")
    src_row = (await session.execute(
        select(StockBalance).where(
            StockBalance.product_id == product.id,
            StockBalance.location_id == src_section.id,
        )
    )).scalar_one_or_none()
    dst_row = (await session.execute(
        select(StockBalance).where(
            StockBalance.product_id == product.id,
            StockBalance.location_id == dst_section.id,
        )
    )).scalar_one_or_none()
    assert src_row is None, "Source StockBalance row should be deleted (balance=0)"
    assert dst_row is None, "Destination StockBalance row should be deleted (balance=0)"

    await assert_no_invariants_violations(session, context="after-cancel")
    await assert_no_stock_ledger_invariants_violations(session, context="after-cancel")


@pytest.mark.asyncio
async def test_cancel_transfer_idempotency_no_duplicate_compensations(
    client, session
) -> None:
    """Повторный cancel (status guard → "already cancelled") не плодит
    дублей компенсаций. После второго вызова по-прежнему 2 StockTransaction
    (1 оригинал + 1 компенсация), не 3+.
    """
    user = await _make_user(session, "tx-dw-cidem@test.local")
    fx = await _make_two_ghp_route(session, sku="TX-DW-CIDM", qty=Decimal("4"))
    await _release_via_take_to_work(client, fx["position"].id)
    tasks = (await session.execute(
        select(WorkTask).order_by(WorkTask.id.asc())
    )).scalars().all()
    src_task, dst_task = tasks[0], tasks[1]

    await _issue_complete_first_task(
        client, session, user, src_task.id, Decimal("4"),
        complete_key="tx-dw-cidem:complete",
    )
    send = await client.post(
        "/api/transfers",
        json={
            "from_task_id": src_task.id,
            "to_task_id": dst_task.id,
            "quantity": "4",
            "idempotency_key": "tx-dw-cidem:send",
        },
        headers=_auth_headers(user),
    )
    assert send.status_code == 200, send.text
    transfer_id = send.json()["transfer_id"]

    first_cancel = await client.post(
        f"/api/transfers/{transfer_id}/cancel", headers=_auth_headers(user)
    )
    assert first_cancel.status_code == 200, first_cancel.text
    assert first_cancel.json()["status"] == "cancelled"

    after_first = await _stock_txs_for_transfer(session, transfer_id)
    assert len(after_first) == 2, (
        f"After first cancel: expected 2 (1 orig + 1 comp), got {len(after_first)}"
    )

    # Повторный cancel — status guard возвращает "cancelled" без действий.
    second_cancel = await client.post(
        f"/api/transfers/{transfer_id}/cancel", headers=_auth_headers(user)
    )
    assert second_cancel.status_code == 200, second_cancel.text
    assert second_cancel.json()["status"] == "cancelled"

    after_second = await _stock_txs_for_transfer(session, transfer_id)
    assert len(after_second) == 2, (
        f"Replay cancel must not create duplicate compensations; got {len(after_second)}"
    )

    await assert_no_stock_ledger_invariants_violations(
        session, context="after-cancel-replay"
    )


# ─── tests: correct_transfer → in-place quantity update ─────────────────────


@pytest.mark.asyncio
async def test_correct_transfer_updates_stock_transaction_quantity(
    client, session
) -> None:
    """``correct_transfer`` синхронно меняет quantity у активной
    StockTransaction (``compensates_tx_id IS NULL``). Контролируемое
    mutable-исключение из append-only, чтобы инвариант S6
    (``SUM(active TRANSFER_SEND qty) == sent_quantity``) выполнялся
    после правки.
    """
    user = await _make_user(session, "tx-dw-corr@test.local")
    fx = await _make_two_ghp_route(session, sku="TX-DW-CORR", qty=Decimal("100"))
    await _release_via_take_to_work(client, fx["position"].id)
    tasks = (await session.execute(
        select(WorkTask).order_by(WorkTask.id.asc())
    )).scalars().all()
    src_task, dst_task = tasks[0], tasks[1]

    await _issue_complete_first_task(
        client, session, user, src_task.id, Decimal("100"),
        complete_key="tx-dw-corr:complete",
    )
    send = await client.post(
        "/api/transfers",
        json={
            "from_task_id": src_task.id,
            "to_task_id": dst_task.id,
            "quantity": "50",
            "idempotency_key": "tx-dw-corr:send",
        },
        headers=_auth_headers(user),
    )
    assert send.status_code == 200, send.text
    transfer_id = send.json()["transfer_id"]

    correct = await client.put(
        f"/api/transfers/{transfer_id}",
        json={"quantity": 70, "comment": "Increased"},
        headers=_auth_headers(user),
    )
    assert correct.status_code == 200, correct.text
    assert correct.json()["quantity"] == "70"

    active_txs = (
        await session.execute(
            select(StockTransaction).where(
                StockTransaction.transfer_id == transfer_id,
                StockTransaction.compensates_tx_id.is_(None),
            )
        )
    ).scalars().all()
    assert len(active_txs) == 1, (
        f"Expected exactly 1 active StockTransaction after correct; got {len(active_txs)}"
    )
    tx = active_txs[0]
    assert tx.quantity == Decimal("70"), (
        f"Active StockTransaction qty={tx.quantity} after correct should be 70"
    )
    assert tx.reason == Reason.transfer_send

    # И в ledger по-прежнему только эта одна активная tx (compensations нет).
    all_txs = await _stock_txs_for_transfer(session, transfer_id)
    assert len(all_txs) == 1

    # S6: SUM(active TRANSFER_SEND) == sent_quantity == 70.
    await assert_no_stock_ledger_invariants_violations(session, context="after-correct")


# ─── tests: auto_create_transfer_after_complete ────────────────────────────


@pytest.mark.asyncio
async def test_auto_create_transfer_after_complete_writes_stock_tx(
    client, session
) -> None:
    """``auto_create_transfer_after_complete`` (``post_factum=True``) пишет
    1 StockTransaction на созданный auto-transfer (та же ledger-геометрия
    ``from=src → to=dst``, ``reason=TRANSFER_SEND``) с
    ``is_post_factum=True``.
    """
    user = await _make_user(session, "tx-dw-auto@test.local")
    fx = await _make_two_ghp_route(session, sku="TX-DW-AUTO", qty=Decimal("6"))
    await _release_via_take_to_work(client, fx["position"].id)
    tasks = (await session.execute(
        select(WorkTask).order_by(WorkTask.id.asc())
    )).scalars().all()
    src_task = tasks[0]
    src_section, dst_section = fx["sections"][0], fx["sections"][1]
    product = fx["product"]

    # Issue + complete на source (без auto_transfer_next — вызываем хелпер
    # напрямую, чтобы изолированно проверить его поведение).
    await _issue_complete_first_task(
        client, session, user, src_task.id, Decimal("6"),
        complete_key="tx-dw-auto:complete",
    )

    # Прямой вызов хелпера — имитирует путь из complete_task с
    # auto_transfer_next=True (см. operations_tasks.py:344-353).
    result = await auto_create_transfer_after_complete(
        session,
        from_task=src_task,
        good_quantity=Decimal("6"),
        actor_id=user.id,
        idempotency_key="tx-dw-auto:auto-transfer",
        comment="Авто-перемещение после завершения",
    )
    assert result is not None
    assert result.get("idempotent_replay") is not True
    transfer_id = result["transfer_id"]

    # На auto-transfer записана ровно 1 StockTransaction.
    stock_txs = await _stock_txs_for_transfer(session, transfer_id)
    assert len(stock_txs) == 1, (
        f"auto_create_transfer_after_complete must write 1 StockTransaction; got {len(stock_txs)}"
    )

    # Transfer помечен как post_factum — StockTransaction наследует is_post_factum.
    tx = stock_txs[0]
    assert tx.is_post_factum is True
    assert tx.reason == Reason.transfer_send
    assert tx.from_location_id == src_section.id
    assert tx.to_location_id == dst_section.id
    assert tx.task_id == src_task.id
    assert tx.quantity == Decimal("6")
    assert tx.compensates_tx_id is None

    # Нет split-геометрии: TRANSFER_RECEIVE в auto-transfer тоже не пишется.
    receive_txs = [t for t in stock_txs if t.reason == Reason.transfer_receive]
    assert receive_txs == [], "TRANSFER_RECEIVE must not be written by auto-transfer"

    # Балансы сходятся с post_factum-логикой.
    assert (await _balance_qty(session, product.id, src_section.id)) == Decimal("-6")
    assert (await _balance_qty(session, product.id, dst_section.id)) == Decimal("6")

    await assert_no_stock_ledger_invariants_violations(session, context="after-auto")


# ─── tests: full e2e cycle ──────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_stock_invariants_hold_after_full_transfer_cycle(client, session) -> None:
    """Полный цикл e2e: complete → transfer_send → correct → cancel.
    После КАЖДОГО шага инварианты S1..S6 должны выполняться. Это
    ловит регрессию, если кто-то забудет пересчитать проекции при
    рефакторинге.
    """
    user = await _make_user(session, "tx-dw-cycle@test.local")
    fx = await _make_two_ghp_route(session, sku="TX-DW-CYCL", qty=Decimal("100"))
    await _release_via_take_to_work(client, fx["position"].id)
    tasks = (await session.execute(
        select(WorkTask).order_by(WorkTask.id.asc())
    )).scalars().all()
    src_task, dst_task = tasks[0], tasks[1]
    src_section, dst_section = fx["sections"][0], fx["sections"][1]
    product = fx["product"]

    # Step 1: complete
    await _issue_complete_first_task(
        client, session, user, src_task.id, Decimal("100"),
        complete_key="tx-dw-cycl:complete",
    )
    await assert_no_stock_ledger_invariants_violations(session, context="after-complete")

    # Step 2: transfer_send (50)
    send = await client.post(
        "/api/transfers",
        json={
            "from_task_id": src_task.id,
            "to_task_id": dst_task.id,
            "quantity": "50",
            "idempotency_key": "tx-dw-cycl:send",
        },
        headers=_auth_headers(user),
    )
    assert send.status_code == 200, send.text
    transfer_id = send.json()["transfer_id"]
    await assert_no_stock_ledger_invariants_violations(session, context="after-send")
    assert (await _balance_qty(session, product.id, src_section.id)) == Decimal("-50")
    assert (await _balance_qty(session, product.id, dst_section.id)) == Decimal("50")

    # Step 3: correct (50 → 70)
    correct = await client.put(
        f"/api/transfers/{transfer_id}",
        json={"quantity": 70, "comment": "Bump"},
        headers=_auth_headers(user),
    )
    assert correct.status_code == 200, correct.text
    await assert_no_stock_ledger_invariants_violations(session, context="after-correct")
    # StockBalance пересчитан, активная StockTransaction имеет qty=70.
    assert (await _balance_qty(session, product.id, src_section.id)) == Decimal("-70")
    assert (await _balance_qty(session, product.id, dst_section.id)) == Decimal("70")

    # Step 4: cancel — балансы возвращаются к 0
    cancel = await client.post(
        f"/api/transfers/{transfer_id}/cancel", headers=_auth_headers(user)
    )
    assert cancel.status_code == 200, cancel.text
    await assert_no_invariants_violations(session, context="after-cancel")
    await assert_no_stock_ledger_invariants_violations(session, context="after-cancel")
    assert (await _balance_qty(session, product.id, src_section.id)) == Decimal("0")
    assert (await _balance_qty(session, product.id, dst_section.id)) == Decimal("0")
