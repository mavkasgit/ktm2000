"""Т6 (#106): чистые budget-формулы + intentional breaking plain-семантики.

Pure-часть (без БД) проверяет ``app.transfers.budget`` напрямую. DB-часть
фиксирует намеренный семантический сдвиг: plain-бюджет = completed −
transferred; ``received`` в бюджете больше не участвует (маркер-комментарий
``T6: received no longer contributes to plain transfer budget``).
"""
from __future__ import annotations

from decimal import Decimal

import pytest
from sqlalchemy import select

from app.models.section import Section
from app.models.work_task import WorkTask
from app.stock import Reason, StockCommand, StockCommandService
from app.transfers.budget import (
    remaining_plain,
    remaining_stock,
    remaining_transform,
)
from app.transfers.services import correct_transfer, transfer_send
from tests.stock.test_transfer_stage2 import _make_two_ghp_setup
from tests.test_integrity_invariants import (
    _release_via_take_to_work,
    assert_no_invariants_violations,
)

# ─── PURE budget-тесты (без БД) ─────────────────────────────────────────────


def test_remaining_plain_full_budget() -> None:
    assert remaining_plain(Decimal("5"), Decimal("0")) == Decimal("5")


def test_remaining_plain_partial_transferred() -> None:
    assert remaining_plain(Decimal("5"), Decimal("2")) == Decimal("3")


def test_remaining_plain_clamped_at_zero() -> None:
    assert remaining_plain(Decimal("5"), Decimal("7")) == Decimal("0")


def test_remaining_plain_zero_completed() -> None:
    assert remaining_plain(Decimal("0"), Decimal("0")) == Decimal("0")


def test_remaining_transform_full_budget() -> None:
    assert remaining_transform(Decimal("100"), Decimal("0")) == Decimal("100")


def test_remaining_transform_partial() -> None:
    assert remaining_transform(Decimal("100"), Decimal("40")) == Decimal("60")


def test_remaining_transform_clamped_at_zero() -> None:
    assert remaining_transform(Decimal("5"), Decimal("7")) == Decimal("0")


def test_remaining_stock_limited_by_physical_stock() -> None:
    assert remaining_stock(Decimal("5"), Decimal("3")) == Decimal("3")


def test_remaining_stock_limited_by_plan_remaining() -> None:
    assert remaining_stock(Decimal("2"), Decimal("5")) == Decimal("2")


# ─── DB-хелперы ─────────────────────────────────────────────────────────────


async def _make_plain_task_budget(
    session,
    client,
    *,
    sku: str,
    completed: Decimal,
    received: Decimal,
) -> dict:
    """Plain (non-stock, non-transform) src task: ``received`` на секции,
    из них ``completed`` завершено. Возвращает from/to task и user."""
    setup = await _make_two_ghp_setup(session, sku=sku, qty=received)
    await _release_via_take_to_work(client, setup["position"].id)
    tasks = (await session.execute(
        select(WorkTask).order_by(WorkTask.id)
    )).scalars().all()
    assert len(tasks) >= 2
    src, dst = tasks[0], tasks[1]

    stock = Section(
        code=f"{sku}-STK", name="Stock", type="raw_stock", is_active=True, sort_order=0,
    )
    session.add(stock)
    await session.flush()

    svc = StockCommandService()
    await svc.record(session, StockCommand(
        product_id=src.product_id,
        from_location_id=None,
        to_location_id=stock.id,
        quantity=received,
        reason=Reason.MANUAL_IN,
        created_by=setup["user"].id,
    ))
    # received: материал на секции источника (issued).
    await svc.record(session, StockCommand(
        product_id=src.product_id,
        from_location_id=stock.id,
        to_location_id=src.section_id,
        quantity=received,
        reason=Reason.TRANSFER_RECEIVE,
        task_id=src.id,
        created_by=setup["user"].id,
    ))
    # completed: только часть received реально завершена.
    await svc.record(session, StockCommand(
        product_id=src.product_id,
        from_location_id=src.section_id,
        to_location_id=src.section_id,
        quantity=completed,
        reason=Reason.COMPLETE,
        task_id=src.id,
        source_ref="test_seed",
        created_by=setup["user"].id,
    ))
    await session.flush()
    return {"from_task_id": src.id, "to_task_id": dst.id, "user": setup["user"]}


# ─── Intentional breaking: plain-бюджет без received ────────────────────────


@pytest.mark.asyncio
async def test_plain_transfer_budget_excludes_received(client, session) -> None:
    """T6 intentional breaking: plain-бюджет = completed − transferred.

    НОВЫЙ ИНВАРИАНТ (T6: received no longer contributes to plain transfer
    budget): received не расширяет бюджет передачи. Сценарий completed=5,
    received=10, transferred=0 → transfer 5 ПРИНЯТ, transfer 6 ОТКЛОНЁН
    (guard transferable == 5). Раньше бюджет был completed + received −
    transferred = 15, и обе передачи прошли бы.
    """
    ctx = await _make_plain_task_budget(
        session, client, sku="BUDGBRK", completed=Decimal("5"), received=Decimal("10"),
    )

    # Первая передача 5 — укладывается в новый бюджет (completed 5, transferred 0).
    r1 = await transfer_send(
        session,
        from_task_id=ctx["from_task_id"],
        to_task_id=ctx["to_task_id"],
        quantity=Decimal("5"),
        actor_id=ctx["user"].id,
    )
    await session.commit()
    assert r1["status"] == "accepted"

    # Вторая передача 6 — превышение: бюджет исчерпан (5 − 5 = 0), несмотря
    # на неиспользованный received 5.
    with pytest.raises(ValueError, match="exceeds transferable"):
        await transfer_send(
            session,
            from_task_id=ctx["from_task_id"],
            to_task_id=ctx["to_task_id"],
            quantity=Decimal("6"),
            actor_id=ctx["user"].id,
        )
    await session.commit()
    await assert_no_invariants_violations(session, context="plain-received-excluded")


# ─── Correction regression: old_quantity возвращается ровно один раз ────────


@pytest.mark.asyncio
async def test_correct_transfer_returns_old_quantity_once(client, session) -> None:
    """Correction regression (T6): old_quantity возвращается в доступный
    бюджет ровно один раз — нет двойного кредитования.

    Сценарий: completed=10, received=10. Передали 3, скорректировали вверх до
    5 (доступно = 10 − 3 + 3 old = 10). Затем добили бюджет передачей 5 и
    попытались скорректировать вверх ещё раз: доступно = 0 + 5 old = 5 < 6 →
    отказ. Если бы old_quantity кредитовался дважды, коррекция до 6 прошла бы.
    """
    ctx = await _make_plain_task_budget(
        session, client, sku="BUDGCOR", completed=Decimal("10"), received=Decimal("10"),
    )

    r1 = await transfer_send(
        session,
        from_task_id=ctx["from_task_id"],
        to_task_id=ctx["to_task_id"],
        quantity=Decimal("3"),
        actor_id=ctx["user"].id,
    )
    await session.commit()
    # 3 → 5: доступно = (10 − 3) + 3 old = 10 ≥ 5 — ровно одно кредитование.
    await correct_transfer(
        session,
        transfer_id=r1["transfer_id"],
        new_quantity=Decimal("5"),
        actor_id=ctx["user"].id,
    )
    await session.commit()

    # Бюджет = 10 − 5 = 5 — добиваем весь plain-бюджет.
    r2 = await transfer_send(
        session,
        from_task_id=ctx["from_task_id"],
        to_task_id=ctx["to_task_id"],
        quantity=Decimal("5"),
        actor_id=ctx["user"].id,
    )
    await session.commit()

    # Бюджет исчерпан: ещё передача невозможна.
    with pytest.raises(ValueError, match="exceeds transferable"):
        await transfer_send(
            session,
            from_task_id=ctx["from_task_id"],
            to_task_id=ctx["to_task_id"],
            quantity=Decimal("1"),
            actor_id=ctx["user"].id,
        )

    # Коррекция 5 → 6: доступно = 0 + 5 old = 5 < 6 → отказ.
    # Двойное кредитование old_quantity дало бы 10 и пропустило бы это.
    with pytest.raises(ValueError, match="exceeds transferable"):
        await correct_transfer(
            session,
            transfer_id=r2["transfer_id"],
            new_quantity=Decimal("6"),
            actor_id=ctx["user"].id,
        )
    await session.commit()
    await assert_no_invariants_violations(session, context="correct-old-quantity-once")
