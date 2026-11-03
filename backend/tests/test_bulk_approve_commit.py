"""Регресс на долговечность массового утверждения позиций.

`approve_position` коммитит САМ до формирования ответа, потому что `get_db`
коммитит уже ПОСЛЕ ответа (см. докстринг `app/core/database.py`). Раньше
`bulk_approve_positions` не коммитил вовсе: клиент получал 200 со списком
успехов и сразу перечитывал план — видел незакоммиченные статусы.

Пакет объявляет `Truncation`: код под тестом ходит в базу своим соединением,
поэтому данные обязаны быть реально закоммичены, чтобы отдельное
соединение-читатель их увидело (в общей транзакции dbcleaner они были бы
невидимы по MVCC). Чистить список таблиц руками больше не нужно —
`TRUNCATE … RESTART IDENTITY CASCADE` возвращает базу к базовой линии.
"""
from __future__ import annotations

from collections.abc import AsyncIterator

import pytest
from app.core.database import get_db
from app.main import app
from app.models.production_plan import (
    PlanPosition,
    PlanPositionStatus,
    ProductionPlan,
    ProductionPlanStatus,
)
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from tests import dbcleaner
from tests.test_bulk_planning import (
    _auth_headers,
    _make_plan_with_positions,
    _make_user,
)

# Своё соединение у кода под тестом -> изоляция коммитами + TRUNCATE после теста.
DB_STRATEGY = dbcleaner.STRATEGY_TRUNCATION
pytestmark = pytest.mark.usefixtures("cleaner_reset")


async def _call_bulk_approve(
    cleaner: dbcleaner.Cleaner,
    *,
    plan_id: int,
    headers: dict[str, str],
    body: dict,
) -> object:
    """Вызывает bulk-approve с зависимостью, которая НИЧЕГО не коммитит на выходе.

    Это ключ к тесту: teardown делает rollback, поэтому выживает ровно то,
    что обработчик закоммитил сам. Именно это и должно быть устойчивым к
    моменту ответа — «отложенный» коммит `get_db` после ответа тут не
    подменяет проверку, а убирается из неё намеренно.
    """

    async def override_get_db() -> AsyncIterator[AsyncSession]:
        async with cleaner.session() as db:
            yield db

    app.dependency_overrides[get_db] = override_get_db
    try:
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as ac:
            response = await ac.post(
                f"/api/production-plans/{plan_id}/positions/bulk-approve",
                json=body,
                headers=headers,
            )
    finally:
        app.dependency_overrides.pop(get_db, None)
    return response


async def _read_committed(
    cleaner: dbcleaner.Cleaner, position_ids: list[int]
) -> list[str]:
    """Читает статусы с соединения, которое видит только закоммиченное."""
    async with cleaner.session() as reader:
        rows = (
            await reader.execute(
                select(PlanPosition.id, PlanPosition.status)
                .where(PlanPosition.id.in_(position_ids))
                .order_by(PlanPosition.id)
            )
        ).all()
    return [status.value for _, status in rows]


@pytest.mark.asyncio
async def test_bulk_approve_is_durable_before_response(
    cleaner: dbcleaner.Cleaner,
) -> None:
    """Массовое утверждение обязано быть закоммичено ДО ответа."""
    sku = "FG-BULK-COMMIT"
    async with cleaner.session() as setup:
        user = await _make_user(setup, "bulk-commit@test.local")
        plan, positions, _ = await _make_plan_with_positions(setup, sku, 3)
        await setup.commit()
        plan_id = plan.id
        position_ids = [p.id for p in positions]
        headers = _auth_headers(user)

    response = await _call_bulk_approve(
        cleaner,
        plan_id=plan_id,
        headers=headers,
        body={"ids": position_ids, "force": False},
    )
    assert response.status_code == 200, response.text
    results = response.json()["results"]
    assert [item["status"] for item in results] == ["success"] * 3, results

    assert await _read_committed(cleaner, position_ids) == [
        PlanPositionStatus.approved.value
    ] * 3

    async with cleaner.session() as reader:
        plan_status = await reader.scalar(
            select(ProductionPlan.status).where(ProductionPlan.id == plan_id)
        )
    assert plan_status == ProductionPlanStatus.approved


@pytest.mark.asyncio
async def test_bulk_approve_commits_successes_despite_failed_item(
    cleaner: dbcleaner.Cleaner,
) -> None:
    """Ошибка по одному id не должна уносить успешные позиции этой же пачки.

    Страховка от «половинного» фикса: коммит внутри цикла или внутри
    savepoint привёл бы к тому, что при `failed`-элементе весь батч откатывается.
    """
    sku = "FG-BULK-MIXED"
    async with cleaner.session() as setup:
        user = await _make_user(setup, "bulk-commit-mixed@test.local")
        plan, positions, _ = await _make_plan_with_positions(setup, sku, 3)
        await setup.commit()
        plan_id = plan.id
        position_ids = [p.id for p in positions]
        ok_ids = position_ids[:2]
        headers = _auth_headers(user)

    # 999_999 не существует -> approve_plan_position бросает ValueError,
    # savepoint откатывается, остальные два обязаны уцелеть и в БД.
    response = await _call_bulk_approve(
        cleaner,
        plan_id=plan_id,
        headers=headers,
        body={"ids": [ok_ids[0], 999_999, ok_ids[1]], "force": False},
    )
    assert response.status_code == 200, response.text
    results = response.json()["results"]
    assert [item["status"] for item in results] == ["success", "failed", "success"], results

    assert await _read_committed(cleaner, position_ids) == [
        PlanPositionStatus.approved.value,
        PlanPositionStatus.approved.value,
        PlanPositionStatus.draft.value,
    ]
