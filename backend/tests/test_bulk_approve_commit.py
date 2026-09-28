"""Регресс на долговечность массового утверждения позиций.

`approve_position` коммитит САМ до формирования ответа, потому что `get_db`
коммитит уже ПОСЛЕ ответа (см. докстринг `app/core/database.py`). Раньше
`bulk_approve_positions` не коммитил вовсе: клиент получал 200 со списком
успехов и сразу перечитывал план — видел незакоммиченные статусы.

Тесты этой модели НЕ даёт проверить обычная `session`-фикстура: её
транзакция откатывается в teardown, а `client` переиспользует ту же сессию,
поэтому чтение «снаружи» эндпоинта всегда видит и несохранённое. Здесь
сценарий строится на СВОИХ соединениях с настоящими коммитами, а проверка
идёт с отдельного соединения, которое физически не может увидеть
незакоммиченные данные.
"""
from __future__ import annotations

from contextlib import asynccontextmanager
from typing import AsyncIterator

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import delete, select, text
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker

from app.core.database import get_db
from app.main import app
from app.models.audit_log import AuditEntityType, AuditLog
from app.models.production_plan import (
    PlanPosition,
    PlanPositionStatus,
    ProductionPlan,
    ProductionPlanStatus,
)
from app.models.product import Product
from app.models.route import ProductionRoute, RouteOperation, RouteStage
from app.models.section import Section
from tests.test_bulk_planning import _auth_headers, _make_plan_with_positions, _make_user


@asynccontextmanager
async def _schema_session(engine: AsyncEngine, schema: str) -> AsyncIterator[AsyncSession]:
    """Сессия на собственном соединении, коммиты которой НАСТОЯЩИЕ.

    `SET search_path` выполняется первым и коммитится: в Postgres SET без
    LOCAL переживает коммит транзакции и держится до конца сессии, поэтому
    все последующие `session.commit()` фиксируют данные по-настоящему, а не
    отпускают savepoint внешней транзакции.
    """
    async with engine.connect() as conn:
        await conn.execute(text(f'SET search_path TO "{schema}"'))
        await conn.commit()
        factory = async_sessionmaker(bind=conn, class_=AsyncSession, expire_on_commit=False)
        async with factory() as db:
            try:
                yield db
            finally:
                await db.rollback()


async def _cleanup(
    engine: AsyncEngine,
    schema: str,
    *,
    plan_id: int,
    position_ids: list[int],
    route_id: int,
    product_id: int,
    user_id: int,
    sku: str,
) -> None:
    async with _schema_session(engine, schema) as db:
        await db.execute(
            delete(AuditLog).where(
                AuditLog.entity_type == AuditEntityType.PLAN_POSITION.value,
                AuditLog.entity_id.in_(position_ids),
            )
        )
        await db.execute(delete(AuditLog).where(AuditLog.user_id == user_id))
        await db.execute(delete(PlanPosition).where(PlanPosition.id.in_(position_ids)))
        await db.execute(delete(ProductionPlan).where(ProductionPlan.id == plan_id))
        await db.execute(
            delete(RouteOperation).where(
                RouteOperation.route_stage_id.in_(
                    select(RouteStage.id).where(RouteStage.route_id == route_id)
                )
            )
        )
        await db.execute(delete(RouteStage).where(RouteStage.route_id == route_id))
        await db.execute(delete(ProductionRoute).where(ProductionRoute.id == route_id))
        await db.execute(delete(Section).where(Section.code.like(f"{sku}-%")))
        await db.execute(delete(Product).where(Product.id == product_id))
        await db.execute(delete(AuditLog).where(AuditLog.section_id.is_not(None)))
        await db.commit()


async def _call_bulk_approve(
    engine: AsyncEngine,
    schema: str,
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
        async with _schema_session(engine, schema) as db:
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


async def _read_committed(engine: AsyncEngine, schema: str, position_ids: list[int]) -> list[str]:
    """Читает статусы с соединения, которое видит только закоммиченное."""
    async with _schema_session(engine, schema) as reader:
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
    engine: AsyncEngine, module_schema_name: str
) -> None:
    """Массовое утверждение обязано быть закоммичено ДО ответа."""
    sku = "FG-BULK-COMMIT"
    async with _schema_session(engine, module_schema_name) as setup:
        user = await _make_user(setup, "bulk-commit@test.local")
        plan, positions, route = await _make_plan_with_positions(setup, sku, 3)
        await setup.commit()
        plan_id = plan.id
        position_ids = [p.id for p in positions]
        route_id = route.id
        product_id = positions[0].product_id
        user_id = user.id
        headers = _auth_headers(user)

    try:
        response = await _call_bulk_approve(
            engine,
            module_schema_name,
            plan_id=plan_id,
            headers=headers,
            body={"ids": position_ids, "force": False},
        )
        assert response.status_code == 200, response.text
        results = response.json()["results"]
        assert [item["status"] for item in results] == ["success"] * 3, results

        assert await _read_committed(engine, module_schema_name, position_ids) == [
            PlanPositionStatus.approved.value
        ] * 3

        async with _schema_session(engine, module_schema_name) as reader:
            plan_status = await reader.scalar(
                select(ProductionPlan.status).where(ProductionPlan.id == plan_id)
            )
        assert plan_status == ProductionPlanStatus.approved
    finally:
        await _cleanup(
            engine,
            module_schema_name,
            plan_id=plan_id,
            position_ids=position_ids,
            route_id=route_id,
            product_id=product_id,
            user_id=user_id,
            sku=sku,
        )


@pytest.mark.asyncio
async def test_bulk_approve_commits_successes_despite_failed_item(
    engine: AsyncEngine, module_schema_name: str
) -> None:
    """Ошибка по одному id не должна уносить успешные позиции этой же пачки.

    Страховка от «половинного» фикса: коммит внутри цикла или внутри
    savepoint привёл бы к тому, что при `failed`-элементе весь батч откатывается.
    """
    sku = "FG-BULK-MIXED"
    async with _schema_session(engine, module_schema_name) as setup:
        user = await _make_user(setup, "bulk-commit-mixed@test.local")
        plan, positions, route = await _make_plan_with_positions(setup, sku, 3)
        await setup.commit()
        plan_id = plan.id
        position_ids = [p.id for p in positions]
        ok_ids = position_ids[:2]
        route_id = route.id
        product_id = positions[0].product_id
        user_id = user.id
        headers = _auth_headers(user)

    try:
        # 999_999 не существует -> approve_plan_position бросает ValueError,
        # savepoint откатывается, остальные два обязаны уцелеть и в БД.
        response = await _call_bulk_approve(
            engine,
            module_schema_name,
            plan_id=plan_id,
            headers=headers,
            body={"ids": [ok_ids[0], 999_999, ok_ids[1]], "force": False},
        )
        assert response.status_code == 200, response.text
        results = response.json()["results"]
        assert [item["status"] for item in results] == ["success", "failed", "success"], results

        assert await _read_committed(engine, module_schema_name, position_ids) == [
            PlanPositionStatus.approved.value,
            PlanPositionStatus.approved.value,
            PlanPositionStatus.draft.value,
        ]
    finally:
        await _cleanup(
            engine,
            module_schema_name,
            plan_id=plan_id,
            position_ids=position_ids,
            route_id=route_id,
            product_id=product_id,
            user_id=user_id,
            sku=sku,
        )
