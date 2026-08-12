"""Cross-path regression (п.2 арх-ревью, тикет #110): компенсация FINAL_RELEASE.

Исторический дефект (ADR-0018): «уже выпущено» читалось разными способами —
gross в ``_released_qty_subquery`` и comp-excluded в ``_net_released_by_dimensions``.
После миграции на canonical net (``net_quantity_expr()``) обе готово-строки
(обычная и production) читают net FINAL_RELEASE: компенсация погашает выпуск,
releasable возвращается к произведённому.

Write-side компенсации выпуска пишется напрямую через ``StockCommandService.record``
(бизнес-операции отмены выпуска пока нет) — легитимный путь, разрешённый ADR-0017.
"""
from __future__ import annotations

from decimal import Decimal

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.stock import Reason, StockCommand, StockCommandService
from app.stock.services import _dimensions_hash_key

from tests.test_integrity_invariants import _auth_headers, _make_user, assert_no_invariants_violations
from tests.test_transfer_dimensions import (
    _complete_saw,
    _make_dim_route_fixture,
    _make_transform_route_fixture,
    _release_via_take_to_work,
    _tasks_for_position,
)

pytestmark = pytest.mark.asyncio


async def _release_and_compensate(
    session: AsyncSession,
    *,
    user_id: int,
    product_id: int,
    task_id: int,
    quantity: Decimal,
    section_id: int,
    dims: dict | None,
    release_tx_id: int,
) -> None:
    """Компенсация выпуска (mirror): зеркалит локации оригинала."""
    svc = StockCommandService()
    await svc.record(
        session,
        StockCommand(
            product_id=product_id,
            from_location_id=None,
            to_location_id=section_id,
            quantity=quantity,
            reason=Reason.FINAL_RELEASE,
            task_id=task_id,
            dimensions=dims,
            compensates_tx_id=release_tx_id,
            created_by=user_id,
        ),
    )
    await session.commit()


async def _seed_plain_final_task(client, session, *, sku: str, qty: Decimal) -> dict:
    """Задача финального этапа (prod2): complete qty → final_release qty.

    Возвращает fx, task, user.
    """
    user = await _make_user(session, f"{sku}@local")
    fx = await _make_dim_route_fixture(session, sku=sku, qty=qty)
    await _release_via_take_to_work(client, fx["position"].id)
    # raw(seq1) → prod1(seq2) → prod2(seq3, final): финальная задача — последняя.
    task = (await _tasks_for_position(session, fx["position"].id))[-1]
    # Финальный этап ещё не получил материал с prod1 (waiting_previous); тест
    # проверяет ready-read-path, поэтому задача должна быть в списке готовых.
    from app.models.work_task import WorkTaskStatus

    task.status = WorkTaskStatus.ready
    await session.commit()

    svc = StockCommandService()
    await svc.record(
        session,
        StockCommand(
            product_id=fx["product"].id,
            from_location_id=None,
            to_location_id=task.section_id,
            quantity=qty,
            reason=Reason.COMPLETE,
            task_id=task.id,
            created_by=user.id,
        ),
    )
    await session.commit()
    return {"fx": fx, "task": task, "user": user}


async def _ready_rows(client, user, section_id: int, task_id: int) -> list[dict]:
    resp = await client.get(
        f"/api/transfers/ready?section_id={section_id}", headers=_auth_headers(user)
    )
    assert resp.status_code == 200, resp.text
    return [i for i in resp.json()["items"] if i["task_id"] == task_id]


async def test_ready_plain_row_net_after_final_release_compensation(client, session) -> None:
    """Обычная задача: после компенсации выпуска ready-строка показывает
    already_transferred=0, transferable вернулся к completed."""
    from app.services.shopfloor.operations_tasks import final_release

    seed = await _seed_plain_final_task(client, session, sku="CRPLN", qty=Decimal("8"))
    task, user = seed["task"], seed["user"]
    fx = seed["fx"]
    prod2 = fx["sections"][2]

    rel = await final_release(session, task_id=task.id, quantity=Decimal("8"), actor_id=user.id)
    await session.commit()
    await _release_and_compensate(
        session,
        user_id=user.id,
        product_id=fx["product"].id,
        task_id=task.id,
        quantity=Decimal("8"),
        section_id=task.section_id,
        dims=task.dimensions,
        release_tx_id=rel["transaction_id"],
    )

    # Оба read-path'а согласованы на net = 0.
    from app.stock.ledger import net_by_reason_by_dimensions
    from app.stock.models import Reason

    grouped = await net_by_reason_by_dimensions(
        session, reason=Reason.FINAL_RELEASE, task_id=task.id
    )
    assert grouped.get(None) == Decimal("0")
    await assert_no_invariants_violations(session, context="ready-plain-net")

    rows = await _ready_rows(client, user, prod2.id, task.id)
    assert len(rows) == 1, f"строка должна остаться (releasable > 0), получил: {rows}"
    row = rows[0]
    assert row["completed_quantity"] == "8"
    # net: 8 − 8 == 0 (не gross 8)
    assert row["already_transferred_quantity"] == "0"
    assert row["transferable_quantity"] == "8"


async def test_ready_production_row_net_after_final_release_compensation(client, session) -> None:
    """Трансформирующая задача: строка выхода (задача, размер) после компенсации
    показывает net=0; обе формы (grouped + ready) согласованы."""
    from app.services.shopfloor.operations_tasks import final_release

    user = await _make_user(session, "cr-prd@local")
    fx = await _make_transform_route_fixture(
        session,
        sku="CRPRD",
        qty=Decimal("100"),
        input_quantity=Decimal("100"),
        input_dimensions={"length_mm": 2700},
        outputs=[{"row_number": 1, "quantity": "100", "dimensions": {"length_mm": 900}}],
        final_transform=True,
    )
    await _release_via_take_to_work(client, fx["position"].id)
    saw_task = (await _tasks_for_position(session, fx["position"].id))[0]
    await _complete_saw(session, saw_task=saw_task, user=user)

    rel = await final_release(
        session, task_id=saw_task.id, quantity=Decimal("100"), actor_id=user.id
    )
    await session.commit()
    await _release_and_compensate(
        session,
        user_id=user.id,
        product_id=fx["product"].id,
        task_id=saw_task.id,
        quantity=Decimal("100"),
        section_id=saw_task.section_id,
        dims={"length_mm": 900},
        release_tx_id=rel["transaction_id"],
    )

    # Production read-path: net FINAL_RELEASE по (задача, размер) == 0.
    from app.stock.ledger import net_by_reason_by_dimensions
    from app.stock.models import Reason

    grouped = await net_by_reason_by_dimensions(
        session, reason=Reason.FINAL_RELEASE, task_id=saw_task.id
    )
    assert grouped.get(_dimensions_hash_key({"length_mm": 900})) == Decimal("0")
    await assert_no_invariants_violations(session, context="ready-prod-net")

    saw_sec = fx["sections"][1]
    rows = await _ready_rows(client, user, saw_sec.id, saw_task.id)
    row_900 = [r for r in rows if r.get("dimensions") == {"length_mm": 900}]
    assert len(row_900) == 1, f"строка выхода 900 должна остаться, получил: {rows}"
    row = row_900[0]
    assert row["completed_quantity"] == "100"
    assert row["already_transferred_quantity"] == "0"
    # produced 100 − released net 0 = 100 (releasable вернулся к произведённому).
    assert row["transferable_quantity"] == "100"


async def test_compensated_final_release_does_not_block_further_release(client, session) -> None:
    """Компенсированный выпуск не блокирует дальнейший выпуск: releasable
    восстанавливается (write-guard читает canonical net)."""
    from app.services.shopfloor.operations_tasks import final_release

    seed = await _seed_plain_final_task(client, session, sku="CRPLN2", qty=Decimal("8"))
    task, user = seed["task"], seed["user"]
    fx = seed["fx"]

    rel1 = await final_release(session, task_id=task.id, quantity=Decimal("8"), actor_id=user.id)
    await session.commit()
    await _release_and_compensate(
        session,
        user_id=user.id,
        product_id=fx["product"].id,
        task_id=task.id,
        quantity=Decimal("8"),
        section_id=task.section_id,
        dims=task.dimensions,
        release_tx_id=rel1["transaction_id"],
    )

    rel2 = await final_release(session, task_id=task.id, quantity=Decimal("8"), actor_id=user.id)
    await session.commit()
    assert rel2["transaction_id"] != rel1["transaction_id"]
    await assert_no_invariants_violations(session, context="compensated-release")
