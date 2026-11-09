"""Батч take-to-work: сбой одной позиции не откатывает уже выпущенные.

Регресс: в обработчике неожиданного исключения стоял `await db.rollback()`
вне `begin_nested()`, поэтому вместе с упавшей позицией откатывались и
успешные, а ответ продолжал сообщать им `success`.
"""

from __future__ import annotations

import pytest
from app.api.routes import production_planning as production_planning_api
from app.models.product import Product, ProductType
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession


@pytest.mark.asyncio
async def test_unexpected_failure_does_not_rollback_earlier_positions(
    client, session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    async def fake_process(db: AsyncSession, position_id: int, **_kwargs):
        if position_id == 2:
            raise RuntimeError("unexpected failure")
        db.add(
            Product(
                sku=f"KEEP-{position_id}",
                name=f"Kept product {position_id}",
                type=ProductType.component,
            )
        )
        await db.flush()
        return production_planning_api.TakeToWorkResult(
            position_id=position_id, status="success"
        )

    monkeypatch.setattr(
        production_planning_api, "_process_position_take_to_work", fake_process
    )

    response = await client.post(
        "/api/production-planning/rows/take-to-work",
        json={"position_ids": [1, 2, 3]},
    )

    assert response.status_code == 200, response.text
    statuses = {
        item["position_id"]: item["status"] for item in response.json()["results"]
    }
    assert statuses == {1: "success", 2: "failed", 3: "success"}

    # Работа соседних позиций обязана пережить откат savepoint'а второй.
    kept = (await session.execute(
        select(Product.sku).where(Product.sku.in_(["KEEP-1", "KEEP-3"]))
    )).scalars().all()
    assert set(kept) == {"KEEP-1", "KEEP-3"}


@pytest.mark.asyncio
async def test_flush_failure_inside_savepoint_leaves_no_tail(
    client, session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Сбой flush внутри savepoint откатывает только свою позицию.

    Позиция 1 добавляет конфликтующий SKU и не делает flush: ошибка всплывает
    на выходе из её savepoint. Контекст-менеджер откатывает только его, сессия
    остаётся рабочей, поэтому позиции 2 и 3 продолжают обрабатываться.
    """
    session.add(
        Product(sku="DUP-FLUSH", name="Existing duplicate", type=ProductType.component)
    )
    await session.flush()

    async def fake_process(db: AsyncSession, position_id: int, **_kwargs):
        if position_id == 1:
            db.add(
                Product(sku="DUP-FLUSH", name="Conflicting", type=ProductType.component)
            )
        elif position_id == 3:
            db.add(
                Product(
                    sku="AFTER-RECOVERY",
                    name="After recovery",
                    type=ProductType.component,
                )
            )
            await db.flush()
        return production_planning_api.TakeToWorkResult(
            position_id=position_id, status="success"
        )

    monkeypatch.setattr(
        production_planning_api, "_process_position_take_to_work", fake_process
    )

    response = await client.post(
        "/api/production-planning/rows/take-to-work",
        json={"position_ids": [1, 2, 3]},
    )

    assert response.status_code == 200, response.text
    statuses = {
        item["position_id"]: item["status"] for item in response.json()["results"]
    }
    assert statuses == {1: "failed", 2: "success", 3: "success"}

    # От неудачной позиции не осталось «хвоста», а успешная — в БД.
    assert await session.scalar(
        select(Product.id).where(Product.sku == "AFTER-RECOVERY")
    ) is not None
    assert await session.scalar(
        select(func.count(Product.id)).where(Product.sku == "DUP-FLUSH")
    ) == 1


@pytest.mark.asyncio
async def test_failure_while_entering_savepoint_does_not_stop_batch(
    client, session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Исключение вне savepoint'а (на входе) не роняет соседние позиции."""
    from sqlalchemy.ext.asyncio import AsyncSession as SAAsyncSession

    original_begin_nested = SAAsyncSession.begin_nested
    calls = {"count": 0}

    def flaky_begin_nested(self):
        calls["count"] += 1
        if calls["count"] == 2:
            raise RuntimeError("savepoint setup failed")
        return original_begin_nested(self)

    async def fake_process(db: AsyncSession, position_id: int, **_kwargs):
        db.add(
            Product(
                sku=f"OUTSIDE-{position_id}",
                name=f"Outside {position_id}",
                type=ProductType.component,
            )
        )
        await db.flush()
        return production_planning_api.TakeToWorkResult(
            position_id=position_id, status="success"
        )

    monkeypatch.setattr(SAAsyncSession, "begin_nested", flaky_begin_nested)
    monkeypatch.setattr(
        production_planning_api, "_process_position_take_to_work", fake_process
    )

    response = await client.post(
        "/api/production-planning/rows/take-to-work",
        json={"position_ids": [1, 2, 3]},
    )

    assert response.status_code == 200, response.text
    statuses = {
        item["position_id"]: item["status"] for item in response.json()["results"]
    }
    assert statuses == {1: "success", 2: "failed", 3: "success"}
    assert await session.scalar(
        select(Product.id).where(Product.sku == "OUTSIDE-1")
    ) is not None
    assert await session.scalar(
        select(Product.id).where(Product.sku == "OUTSIDE-3")
    ) is not None


@pytest.mark.asyncio
async def test_session_level_rollback_marks_previous_success_failed(
    session: AsyncSession,
) -> None:
    """Ветка «сессия неактивна»: откат стирает успехи, ответ это признаёт."""
    results = [
        production_planning_api.TakeToWorkResult(
            position_id=1, status="success", release_batch_id=42
        ),
        production_planning_api.TakeToWorkResult(position_id=2, status="failed"),
    ]

    await production_planning_api._rollback_batch_after_session_error(session, results)

    assert results[0].status == "failed"
    assert results[0].release_batch_id is None
    assert "rolled back" in (results[0].reason or "").lower()
    assert results[1].status == "failed"
