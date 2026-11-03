"""Выдача из общего пула эквивалентов: канонизация и отмена (#393/#395).

Проверяется контракт ADR-0073 п.5: материал списывается с фактического SKU
источника, на задание приходит артикулом задания; отмена зеркалит обе
проводки — источник возвращается на склад, приём снимается с задания.

Инварианты S1/S6/C1/D1 проверяются после выдачи и после отмены: ledger
остаётся единственным источником правды, а группа — только операторским
слоем.
"""
from __future__ import annotations

from decimal import Decimal

from app.models.product import Product, ProductType
from app.models.transfer import Transfer, TransferStatus
from app.models.work_task import WorkTask
from app.stock.models import Reason, StockBalance, StockTransaction
from app.stock.services import StockProjectionManager
from sqlalchemy import select

from tests.helpers.transfers import _make_dim_route_fixture, _seed_balance
from tests.test_integrity_invariants import (
    _auth_headers,
    _make_user,
    assert_no_invariants_violations,
    assert_no_stock_ledger_invariants_violations,
)

RAW_OPS = ["ISSUE_RAW"]


async def _equivalent(session, anchor: Product, sku: str) -> Product:
    product = Product(
        sku=sku,
        name=sku,
        type=ProductType.component,
        unit="pcs",
        is_active=True,
    )
    session.add(product)
    await session.flush()
    anchor.aliases = [sku]
    await session.commit()
    return product


async def _balance_qty(session, *, product_id: int, location_id: int) -> Decimal:
    total = await session.scalar(
        select(StockBalance.balance_qty).where(
            StockBalance.product_id == product_id,
            StockBalance.location_id == location_id,
        )
    )
    return Decimal(total or 0)


async def _transactions(session, reason: Reason) -> list[StockTransaction]:
    return list(
        (
            await session.execute(
                select(StockTransaction)
                .where(StockTransaction.reason == reason)
                .order_by(StockTransaction.id)
            )
        ).scalars().all()
    )


async def test_issue_from_equivalent_pool_and_cancel_restores_source(
    client, session
) -> None:
    """A выдаёт кучу B: send — B, receive — A; отмена возвращает B на склад."""
    fx = await _make_dim_route_fixture(session, sku="ALIASP", qty=Decimal(100))
    raw, _p1, _p2 = fx["sections"]
    user = await _make_user(session, "aliasp@local")
    equivalent = await _equivalent(session, fx["product"], "ALIASP-EQ")

    await _seed_balance(
        session,
        user_id=user.id,
        location_id=raw.id,
        product_id=equivalent.id,
        qty=Decimal(60),
        ops=RAW_OPS,
    )

    resp = await client.post(
        "/api/production-planning/rows/take-to-work",
        json={
            "position_ids": [fx["position"].id],
            "issue": {
                "auto": True,
                "shortage_strategy": "partial",
                "idempotency_key": "aliasp-1",
            },
        },
        headers=_auth_headers(user),
    )
    assert resp.status_code == 200, resp.text
    result = resp.json()["results"][0]
    assert result["status"] == "success", result
    issue_no = result["issue"]["issue_no"]

    transfer = await session.scalar(
        select(Transfer).where(Transfer.issue_no == issue_no)
    )
    assert transfer is not None
    assert transfer.product_id == fx["product"].id, "передача несёт артикул задания"
    assert "источник: ALIASP-EQ (эквивалент)" in (transfer.comment or "")

    sends = await _transactions(session, Reason.TRANSFER_SEND)
    receives = await _transactions(session, Reason.TRANSFER_RECEIVE)
    assert len(sends) == 1 and len(receives) == 1
    assert sends[0].product_id == equivalent.id, "send — фактический SKU источника"
    assert receives[0].product_id == fx["product"].id, "receive — артикул задания"
    # Канонизация на участке (ADR-0073 п.5): расход склада — у send, приход
    # участка — у receive. Иначе на участке остался бы SKU источника B, хотя
    # учёт задания уже под A, и следующая операция искала бы не тот артикул.
    assert sends[0].to_location_id is None, "send не должен класть эквивалент на участок"

    task = await session.get(WorkTask, transfer.to_task_id)
    assert task is not None and task.product_id == fx["product"].id
    assert receives[0].to_location_id == task.section_id, (
        "receive приходит на участок задания под его артикулом"
    )
    cache = await StockProjectionManager().get_task_cache(session, task.id)
    assert cache["received_quantity"] == Decimal(60), (
        "на задании материал учтён под артикулом задания"
    )
    assert await _balance_qty(session, product_id=equivalent.id, location_id=raw.id) == Decimal(0)
    assert await _balance_qty(
        session, product_id=fx["product"].id, location_id=task.section_id
    ) == Decimal(60), "на участке материал лежит под артикулом задания A"
    assert await _balance_qty(
        session, product_id=equivalent.id, location_id=task.section_id
    ) == Decimal(0), "на участке не должно быть SKU источника B"
    await assert_no_invariants_violations(session, context="issue equivalent")
    await assert_no_stock_ledger_invariants_violations(
        session, context="issue equivalent"
    )

    cancel = await client.post(
        f"/api/transfers/issues/{issue_no}/cancel",
        params={"comment": "вернуть эквивалент"},
        headers=_auth_headers(user),
    )
    assert cancel.status_code == 200, cancel.text

    transfer = await session.get(Transfer, transfer.id)
    assert transfer.status == TransferStatus.cancelled
    assert await _balance_qty(
        session, product_id=equivalent.id, location_id=raw.id
    ) == Decimal(60), "отмена вернула фактический SKU источника на склад"
    assert await _balance_qty(
        session, product_id=fx["product"].id, location_id=task.section_id
    ) == Decimal(0), "отмена сняла артикул задания с участка"
    assert await _balance_qty(
        session, product_id=equivalent.id, location_id=task.section_id
    ) == Decimal(0), "на участке не осталось SKU источника"
    cache = await StockProjectionManager().get_task_cache(session, task.id)
    assert cache["received_quantity"] == Decimal(0), "приём снят с задания"
    await assert_no_invariants_violations(session, context="cancel equivalent")
    await assert_no_stock_ledger_invariants_violations(
        session, context="cancel equivalent"
    )
