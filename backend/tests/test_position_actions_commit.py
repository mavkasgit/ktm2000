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

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

import pytest
from app.core.database import get_db
from app.main import app
from app.models.audit_log import AuditAction, AuditEntityType, AuditLog
from app.models.internal_plan import InternalPlan, SectionPlanLine
from app.models.product import Product
from app.models.production_plan import (
    PlanPosition,
    PlanPositionStatus,
    ProductionPlan,
    ProductionPlanStatus,
)
from app.models.route import (
    ProductionRoute,
    RouteOperation,
    RouteStage,
    SectionOperation,
)
from app.models.section import Section
from app.models.work_task import WorkTask, WorkTaskStatus
from httpx import ASGITransport, AsyncClient
from sqlalchemy import delete, select, text
from sqlalchemy import func as sa_func
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker

from tests.test_bulk_approve_commit import _schema_session
from tests.test_bulk_planning import (
    _auth_headers,
    _make_plan_with_positions,
    _make_user,
)


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
        await db.execute(delete(WorkTask).where(WorkTask.product_id == product_id))
        await db.execute(delete(SectionPlanLine).where(SectionPlanLine.product_id == product_id))
        await db.execute(delete(InternalPlan).where(InternalPlan.production_plan_id == plan_id))
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
        # Справочник операций участков живёт отдельной таблицей (ADR-0061:
        # фикстуры регистрируют в нём операции этапов), поэтому секции
        # убираются не раньше своих операций.
        await db.execute(
            delete(SectionOperation).where(
                SectionOperation.section_id.in_(
                    select(Section.id).where(Section.code.like(f"{sku}-%"))
                )
            )
        )
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


@asynccontextmanager
async def _client_with_failing_hard_delete(
    engine: AsyncEngine, schema: str
) -> AsyncIterator[AsyncClient]:
    """Клиент, чья сессия роняет каждый DELETE по ``plan_positions``.

    Имитирует IntegrityError группового hard-delete (TOCTOU между
    классификацией и DELETE): savepoint группы обязан откатиться, API —
    ответить 200 с failed на hard-id, а soft-delete того же батча —
    закоммитить.
    """

    class _FailingHardDeleteSession(AsyncSession):
        async def execute(self, statement, *args, **kwargs):
            if (
                getattr(statement, "is_delete", False)
                and getattr(getattr(statement, "table", None), "name", None)
                == PlanPosition.__tablename__
            ):
                raise RuntimeError("forced plan_positions DELETE failure")
            return await super().execute(statement, *args, **kwargs)

    async def override_get_db() -> AsyncIterator[AsyncSession]:
        async with engine.connect() as conn:
            await conn.execute(text(f'SET search_path TO "{schema}"'))
            await conn.commit()
            factory = async_sessionmaker(
                bind=conn, class_=_FailingHardDeleteSession, expire_on_commit=False
            )
            async with factory() as db:
                try:
                    yield db
                finally:
                    await db.rollback()

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
        # 999_999 не существует: классификация (один SELECT до мутаций)
        # помечает его failed — без исключения и без savepoint'а.
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


@pytest.mark.asyncio
async def test_bulk_delete_positions_hard_group_failure_keeps_soft_results(
    engine: AsyncEngine, module_schema_name: str
) -> None:
    """Сбой hard-группы не должен уносить soft-delete того же батча.

    Групповой DELETE по ``plan_positions`` замокан на исключение (аналог
    IntegrityError по TOCTOU между классификацией и DELETE). Контракт:
    savepoint группы откатывается, hard-id помечаются failed с безопасным
    сообщением (текст исключения наружу не течёт), а soft-delete,
    выполненный ДО savepoint'а, уезжает общим коммитом.
    """
    sku = "FG-BULKDELETE-HARDFAIL"
    async with _schema_session(engine, module_schema_name) as setup:
        user = await _make_user(setup, "bulk-delete-hardfail@test.local")
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
        # `cancelled_count=1`: первая позиция — cancelled (soft), вторая —
        # черновик (hard); DELETE по plan_positions упадёт внутри savepoint'а.
        async with _client_with_failing_hard_delete(engine, module_schema_name) as ac:
            response = await ac.post(
                f"/api/production-plans/{plan_id}/positions/bulk-delete",
                json={"ids": position_ids, "reason": "сбой hard-группы"},
                headers=headers,
            )
        assert response.status_code == 200, response.text
        by_id = {item["id"]: item for item in response.json()["results"]}
        assert by_id[position_ids[0]]["status"] == "success", by_id
        assert by_id[position_ids[1]]["status"] == "failed", by_id
        # Текст исключения наружу не течёт.
        assert by_id[position_ids[1]]["reason"] == "Внутренняя ошибка сервера"

        committed = await _read_committed(engine, module_schema_name, position_ids)
        by_committed = {pid: (status, deleted_at) for pid, status, deleted_at in committed}
        # Soft-delete пережил откат savepoint'а hard-группы и закоммичен.
        assert by_committed[position_ids[0]][0] == PlanPositionStatus.cancelled.value
        assert by_committed[position_ids[0]][1] is not None
        # Hard-delete откатан: черновик на месте, без скрытия.
        assert by_committed[position_ids[1]][0] == PlanPositionStatus.draft.value
        assert by_committed[position_ids[1]][1] is None
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
async def test_bulk_delete_positions_soft_delete_db_error_isolates_and_commits(
    engine: AsyncEngine,
    module_schema_name: str,
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """Реальная ошибка уровня БД в цикле soft-delete не должна абортировать транзакцию батча.

    Батч из 3 soft-id (cancelled) и 1 hard-id (draft):
    - soft[0]: успешен (скрытие)
    - soft[1]: реальный сбой уровня БД (FK violation через SQL в текущей сессии db)
      инжектируется ПОСЛЕ реального soft_delete (установки deleted_at, записи AuditLog
      и отмены WorkTask), имитируя TOCTOU / отказ БД в конце мутации.
    - soft[2]: успешен (скрытие)
    - hard[3]: успешен (жесткое удаление черновика)

    Контракт:
    - soft[0], soft[2] и hard[3] имеют status="success" и закоммичены в БД;
    - soft[1] имеет status="failed" с безопасным reason="Внутренняя ошибка сервера";
    - первичная ошибка в caplog — именно IntegrityError (нарушение FK);
    - откат savepoint откатывает deleted_at, запись аудита и отмену WorkTask для soft[1];
    - вся пачка успешно коммитится, а сессия не уходит в InFailedSqlTransaction.
    """
    import logging
    import app.api.routes.production_plans as prod_plans_route

    caplog.set_level(logging.ERROR)

    sku = "FG-BULKDELETE-SOFTFAIL"
    async with _schema_session(engine, module_schema_name) as setup:
        user = await _make_user(setup, "bulk-delete-softfail@test.local")
        # 3 cancelled (soft-delete), 1 draft (hard-delete)
        plan, positions, route = await _make_plan_with_positions(
            setup, sku, 4, cancelled_count=3
        )
        plan_id = plan.id
        position_ids = [p.id for p in positions]
        route_id = route.id
        product_id = positions[0].product_id
        user_id = user.id
        headers = _auth_headers(user)
        failing_pos_id = position_ids[1]

        # Создаём связанное задание WorkTask для failing-позиции, чтобы проверить откат его отмены
        internal_plan = InternalPlan(production_plan_id=plan_id)
        setup.add(internal_plan)
        await setup.flush()

        route_stage = (
            await setup.execute(
                select(RouteStage).where(RouteStage.route_id == route_id)
            )
        ).scalars().first()

        line = SectionPlanLine(
            internal_plan_id=internal_plan.id,
            plan_position_id=failing_pos_id,
            section_id=route_stage.section_id,
            product_id=product_id,
            route_id=route_id,
            route_stage_id=route_stage.id,
            sequence=1,
            planned_quantity=10,
        )
        setup.add(line)
        await setup.flush()

        task = WorkTask(
            section_plan_line_id=line.id,
            section_id=route_stage.section_id,
            product_id=product_id,
            route_stage_id=route_stage.id,
            planned_quantity=10,
            status=WorkTaskStatus.ready,
        )
        setup.add(task)
        await setup.flush()
        task_id = task.id

        await setup.commit()

    orig_soft_delete = prod_plans_route.soft_delete_cancelled_position

    async def _failing_soft_delete(db, p_plan_id, pos_id, **kwargs):
        # 1. Сначала отрабатывает настоящая soft_delete (deleted_at, log_action, WorkTask -> cancelled)
        res = await orig_soft_delete(db, p_plan_id, pos_id, **kwargs)
        if pos_id == failing_pos_id:
            # 2. Инжектируем падающий SQL: все NOT NULL колонки заполнены валидно,
            # нарушается исключительно внешний ключ (production_plan_id=999999999).
            await db.execute(
                text(
                    "INSERT INTO plan_positions ("
                    "  production_plan_id, product_id, source_type, source_sku, quantity, status, validation_status"
                    ") VALUES ("
                    "  999999999, :prod_id, 'manual', 'INVALID-FK', 1, 'draft', 'valid'"
                    ")"
                ),
                {"prod_id": product_id},
            )
            await db.flush()
        return res

    monkeypatch.setattr(prod_plans_route, "soft_delete_cancelled_position", _failing_soft_delete)

    try:
        async with _non_committing_client(engine, module_schema_name) as ac:
            response = await ac.post(
                f"/api/production-plans/{plan_id}/positions/bulk-delete",
                json={"ids": position_ids, "reason": "проверка изоляции soft-delete"},
                headers=headers,
            )

        assert response.status_code == 200, response.text
        by_id = {item["id"]: item for item in response.json()["results"]}
        assert by_id[position_ids[0]]["status"] == "success", by_id
        assert by_id[position_ids[1]]["status"] == "failed", by_id
        assert by_id[position_ids[1]]["reason"] == "Внутренняя ошибка сервера"
        assert by_id[position_ids[2]]["status"] == "success", by_id
        assert by_id[position_ids[3]]["status"] == "success", by_id

        # Проверяем caplog: первичная ошибка залогирована как IntegrityError (FK violation)
        unexpected_records = [
            r for r in caplog.records
            if "unexpected error for id" in r.message and str(failing_pos_id) in r.message
        ]
        assert len(unexpected_records) == 1, [r.message for r in caplog.records]
        primary_exc = unexpected_records[0].exc_info[1]
        assert isinstance(primary_exc, IntegrityError), repr(primary_exc)
        assert (
            "plan_positions_production_plan_id_fkey" in str(primary_exc).lower()
            or "foreign key" in str(primary_exc).lower()
        ), str(primary_exc)

        # Проверяем committed-состояние через отдельную сессию:
        committed = await _read_committed(engine, module_schema_name, position_ids)
        by_committed = {pid: (status, deleted_at) for pid, status, deleted_at in committed}
        # soft[0] — скрыта
        assert by_committed[position_ids[0]][0] == PlanPositionStatus.cancelled.value
        assert by_committed[position_ids[0]][1] is not None
        # soft[1] (failing): savepoint откатил deleted_at обратно в None!
        assert by_committed[failing_pos_id][0] == PlanPositionStatus.cancelled.value
        assert by_committed[failing_pos_id][1] is None
        # soft[2] — скрыта
        assert by_committed[position_ids[2]][0] == PlanPositionStatus.cancelled.value
        assert by_committed[position_ids[2]][1] is not None
        # hard[3] — физически удалена из таблицы
        assert position_ids[3] not in by_committed

        # Аудит: запись «скрыта из плана» откачена вместе с savepoint (доказывает,
        # что log_action пишет в ту же сессию db и не переживает откат).
        assert await _audit_count(
            engine, module_schema_name, failing_pos_id, AuditAction.DELETE.value
        ) == 0

        # WorkTask: статус откатился обратно в ready, а не остался cancelled
        async with _schema_session(engine, module_schema_name) as reader:
            task_status = await reader.scalar(
                select(WorkTask.status).where(WorkTask.id == task_id)
            )
            assert task_status == WorkTaskStatus.ready
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

