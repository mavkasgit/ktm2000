"""Батч take-to-work: сбой одной позиции не откатывает уже выпущенные.

Регресс: в обработчике неожиданного исключения стоял `await db.rollback()`
вне `begin_nested()`, поэтому вместе с упавшей позицией откатывались и
успешные, а ответ продолжал сообщать им `success`.
"""

from __future__ import annotations

import pytest
from app.api.routes import production_planning as production_planning_api
from app.models.product import Product, ProductType
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession


@pytest.mark.asyncio
async def test_unexpected_failure_does_not_rollback_earlier_positions(
    client, session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    async def fake_process(db: AsyncSession, position_id: int, **_kwargs):
        if position_id == 2:
            raise RuntimeError("unexpected failure")
        db.add(Product(sku="KEEP-ME", name="Kept product", type=ProductType.component))
        await db.flush()
        return production_planning_api.TakeToWorkResult(
            position_id=position_id, status="success"
        )

    monkeypatch.setattr(
        production_planning_api, "_process_position_take_to_work", fake_process
    )

    response = await client.post(
        "/api/production-planning/rows/take-to-work",
        json={"position_ids": [1, 2]},
    )

    assert response.status_code == 200, response.text
    statuses = {
        item["position_id"]: item["status"] for item in response.json()["results"]
    }
    assert statuses == {1: "success", 2: "failed"}

    # Работа первой позиции обязана пережить откат savepoint'а второй.
    kept = await session.scalar(select(Product.id).where(Product.sku == "KEEP-ME"))
    assert kept is not None
