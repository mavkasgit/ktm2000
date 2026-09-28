"""Регресс на долговечность отмены, восстановления и массового удаления позиций.

`get_db` коммитит ПОСЛЕ ответа (докстринг `app/core/database.py`), поэтому
мутирующий эндпоинт обязан коммитить сам до формирования ответа — так уже
сделано в `approve_position` и `bulk_approve_positions`. `cancel_position`,
`restore_position` и `bulk_delete_positions` отвечали раньше, чем изменения
становились видимыми: клиент получал 200 и сразу перечитывал план, где всё
ещё было по-прежнему.

Обычная `session`-фикстура здесь слепа: её внешняя транзакция откатывается в
teardown, а `client` переиспользует ту же сессию, поэтому «чтение снаружи»
эндпоинта всегда видит и несохранённое. Здесь сценарий строится на СВОИХ
соединениях с настоящими коммитами, а проверка идёт с отдельного соединения,
которое по MVCC физически не может увидеть незакоммиченные данные. Зависимость
`get_db` намеренно НЕ коммитит на выходе — иначе тест был бы зелёным и на
сломанной реализации.
"""
from __future__ import annotations

from contextlib import asynccontextmanager
from typing import AsyncIterator

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import delete, func as sa_func, select
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession

from app.core.database import get_db
from app.main import app
from app.models.audit_log import AuditAction, AuditEntityType, AuditLog
from app.models.production_plan import (
    PlanPosition,
    PlanPositionStatus,
    ProductionPlan,
    ProductionPlanStatus,
)
from app.models.product import Product
from app.models.route import ProductionRoute, RouteOperation, RouteStage
from app.models.section import Section
from tests.test_bulk_approve_commit import _schema_session
from tests.test_bulk_planning import _auth_headers, _make_plan_with_positions, _make_user


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


@asynccontextmanager
async def _non_committing_client(
    engine: AsyncEngine, schema: str
) -> AsyncIterator[AsyncClient]:
    """Клиент с `get_db`, который на выходе делает rollback, а не commit.

    Так выживает ровно то, что обработчик закоммитил сам. Отложенный коммит
    `get_db` после ответа тут не подменяет проверку, а убирается из неё.
    """

    async def override_get_db() -> AsyncIterator[AsyncSession]:
        async with _schema_session(engine, schema) as db:
            yield db

    app.dependency_overrides[get_db] = override_get_db
    try:
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as ac:
            yield ac
    finally:
        app.dependency_overrides.pop(get_db, None)


async def _read_committed(
    engine: AsyncEngine, schema: str, position_ids: list[int]
) -> list[tuple[int, str, object]]:
    """Читает позиции с соединения, которое видит только закоммиченное."""
    async with _schema_session(engine, schema) as reader:
        rows = (
            await reader.execute(
                select(PlanPosition.id, PlanPosition.status, PlanPosition.deleted_at)
                .where(PlanPosition.id.in_(position_ids))
                .order_by(PlanPosition.id)
            )
        ).all()
    return [(pid, status.value, deleted_at) for pid, status, deleted_at in rows]


async def _read_plan_status(engine: AsyncEngine, schema: str, plan_id: int):
    async with _schema_session(engine, schema) as reader:
        return await reader.scalar(
            select(ProductionPlan.status).where(ProductionPlan.id == plan_id)
        )


async def _audit_count(
    engine: AsyncEngine, schema: str, position_id: int, action: str
) -> int:
    """Считает закоммиченные записи аудита, видимые со стороны."""
    async with _schema_session(engine, schema) as reader:
        count = await reader.scalar(
            select(sa_func.count())
            .select_from(AuditLog)
            .where(
                AuditLog.entity_type == AuditEntityType.PLAN_POSITION.value,
                AuditLog.entity_id == position_id,
                AuditLog.action == action,
            )
        )
    return int(count or 0)


@pytest.mark.asyncio
async def test_cancel_position_commits_status_before_response(
    engine: AsyncEngine, module_schema_name: str
) -> None:
    """Отмена позиции обязана быть закоммичена ДО ответа."""
    sku = "FG-CANCEL-COMMIT"
    async with _schema_session(engine, module_schema_name) as setup:
        user = await _make_user(setup, "cancel-commit@test.local")
        plan, positions, route = await _make_plan_with_positions(
            setup, sku, 2, status=PlanPositionStatus.approved
        )
        await setup.commit()
        plan_id = plan.id
        position_ids = [p.id for p in positions]
        target_id = position_ids[0]
        route_id = route.id
        product_id = positions[0].product_id
        user_id = user.id
        headers = _auth_headers(user)

    try:
        async with _non_committing_client(engine, module_schema_name) as ac:
            response = await ac.post(
                f"/api/production-plans/{plan_id}/positions/{target_id}/cancel",
                json={"reason": "брак"},
                headers=headers,
            )
        assert response.status_code == 200, response.text
        assert response.json()["status"] == PlanPositionStatus.cancelled.value

        committed = await _read_committed(engine, module_schema_name, position_ids)
        assert committed == [
            (target_id, PlanPositionStatus.cancelled.value, None),
            (position_ids[1], PlanPositionStatus.approved.value, None),
        ]
        # Пересчёт статуса плана обязан уехать тем же коммитом.
        assert await _read_plan_status(engine, module_schema_name, plan_id) == (
            ProductionPlanStatus.approved
        )
        # Аудит отмены — часть того же коммита.
        assert await _audit_count(
            engine, module_schema_name, target_id, AuditAction.CANCEL.value
        ) == 1
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
async def test_restore_position_commits_status_before_response(
    engine: AsyncEngine, module_schema_name: str
) -> None:
    """Восстановление позиции обязано быть закоммичено ДО ответа."""
    sku = "FG-RESTORE-COMMIT"
    async with _schema_session(engine, module_schema_name) as setup:
        user = await _make_user(setup, "restore-commit@test.local")
        plan, positions, route = await _make_plan_with_positions(
            setup, sku, 1, status=PlanPositionStatus.cancelled
        )
        target_id = positions[0].id
        # История отмены — обязательное условие `restore_plan_position`.
        setup.add(
            AuditLog(
                user_id=user.id,
                user_name=user.full_name,
                status="success",
                title="Отмена позиции",
                message="подготовка",
                action=AuditAction.CANCEL.value,
                entity_type=AuditEntityType.PLAN_POSITION.value,
                entity_id=target_id,
                changes={
                    "before": {"status": PlanPositionStatus.approved.value},
                    "after": {"status": PlanPositionStatus.cancelled.value},
                },
            )
        )
        await setup.commit()
        plan_id = plan.id
        position_ids = [target_id]
        route_id = route.id
        product_id = positions[0].product_id
        user_id = user.id
        headers = _auth_headers(user)

    try:
        async with _non_committing_client(engine, module_schema_name) as ac:
            response = await ac.post(
                f"/api/production-plans/{plan_id}/positions/{target_id}/restore",
                json={},
                headers=headers,
            )
        assert response.status_code == 200, response.text
        assert response.json()["status"] == PlanPositionStatus.approved.value

        assert await _read_committed(engine, module_schema_name, position_ids) == [
            (target_id, PlanPositionStatus.approved.value, None)
        ]
        assert await _read_plan_status(engine, module_schema_name, plan_id) == (
            ProductionPlanStatus.approved
        )
        assert await _audit_count(
            engine, module_schema_name, target_id, AuditAction.RESTORE.value
        ) == 1
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
async def test_bulk_delete_positions_commits_batch_before_response(
    engine: AsyncEngine, module_schema_name: str
) -> None:
    """Массовое удаление обязано быть закоммичено ДО ответа.

    Один коммит закрывает обе ветки батча: hard-delete черновика и soft-delete
    (скрытие) отменённой позиции.
    """
    sku = "FG-BULKDELETE-COMMIT"
    async with _schema_session(engine, module_schema_name) as setup:
        user = await _make_user(setup, "bulk-delete-commit@test.local")
        plan, positions, route = await _make_plan_with_positions(
            setup, sku, 2, cancelled_count=1
        )
        await setup.commit()
        plan_id = plan.id
        position_ids = [p.id for p in positions]
        route_id = route.id
        product_id = positions[0].product_id
        user_id = user.id
        headers = _auth_headers(user)

    try:
        async with _non_committing_client(engine, module_schema_name) as ac:
            response = await ac.post(
                f"/api/production-plans/{plan_id}/positions/bulk-delete",
                json={"ids": position_ids, "reason": "уборка"},
                headers=headers,
            )
        assert response.status_code == 200, response.text
        results = response.json()["results"]
        assert [item["status"] for item in results] == ["success", "success"], results

        committed = await _read_committed(engine, module_schema_name, position_ids)
        by_id = {pid: (status, deleted_at) for pid, status, deleted_at in committed}
        # `cancelled_count=1` делает ПЕРВУЮ позицию отменённой, вторую — черновиком.
        # Отменённая скрыта: строка есть, deleted_at заполнен.
        assert by_id[position_ids[0]][0] == PlanPositionStatus.cancelled.value
        assert by_id[position_ids[0]][1] is not None
        # Черновик удалён насовсем: строки в БД нет вовсе.
        assert position_ids[1] not in by_id
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
async def test_bulk_delete_positions_commits_successes_despite_failed_item(
    engine: AsyncEngine, module_schema_name: str
) -> None:
    """`failed`-элемент не должен уносить успехи той же пачки.

    Страховка от «половинного» фикса: коммит внутри цикла или внутри savepoint
    привёл бы к откату всего батча при первой же ошибке.
    """
    sku = "FG-BULKDELETE-MIXED"
    async with _schema_session(engine, module_schema_name) as setup:
        user = await _make_user(setup, "bulk-delete-mixed@test.local")
        plan, positions, route = await _make_plan_with_positions(setup, sku, 2)
        await setup.commit()
        plan_id = plan.id
        position_ids = [p.id for p in positions]
        route_id = route.id
        product_id = positions[0].product_id
        user_id = user.id
        headers = _auth_headers(user)

    try:
        # 999_999 не существует -> ValueError внутри savepoint'а.
        async with _non_committing_client(engine, module_schema_name) as ac:
            response = await ac.post(
                f"/api/production-plans/{plan_id}/positions/bulk-delete",
                json={"ids": [position_ids[0], 999_999, position_ids[1]]},
                headers=headers,
            )
        assert response.status_code == 200, response.text
        results = response.json()["results"]
        assert [item["status"] for item in results] == [
            "success",
            "failed",
            "success",
        ], results

        committed = await _read_committed(engine, module_schema_name, position_ids)
        assert committed == []
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
