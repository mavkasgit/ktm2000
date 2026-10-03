"""Регресс на долговечность импорта плана (#287).

`POST /api/imports/excel/simulate` (и его файловый собрат `/excel`) отдаёт в
ответе `production_plan_id`/`change_set_id`, по которым клиент СРАЗУ бьёт
`POST /api/production-plans/{id}/change-sets/{cid}/apply`. Если эндпоинт не
коммитит сам, коммит делает зависимость `get_db` — а он, по докстрингу
`core/database.py` и по устройству `fastapi.routing.request_response`,
выполняется ПОСЛЕ отправки ответа. Тогда `apply` не находит план и отдаёт 404
«Production plan not found» — ровно тот флейк, что заведён тикетом #287.

Харнесс тот же, что у `test_bulk_approve_commit.py`: зависимость подменяется
такой, чей teardown делает **rollback**, поэтому выживает ровно то, что
обработчик закоммитил сам. Отложенный коммит `get_db` тут не подменяет
проверку, а убирается из неё намеренно.
"""
from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

import pytest
from app.core.database import get_db
from app.main import app
from app.models.product import Product, ProductLength, ProductType
from app.models.production_plan import PlanChangeSet, ProductionPlan
from app.models.route import ProductionRoute, RouteOperation, RouteStage
from app.models.section import Section
from app.models.user import User, UserRole
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker

SIMULATE_URL = "/api/imports/excel/simulate"
SKU = "ЮП-COMMIT-287"


@asynccontextmanager
async def _durable_session(engine: AsyncEngine, schema: str) -> AsyncIterator[AsyncSession]:
    """Сессия на собственном соединении, коммиты которой НАСТОЯЩИЕ.

    `SET search_path` выполняется первым и коммитится: в Postgres SET без
    LOCAL переживает коммит транзакции, поэтому последующие `session.commit()`
    фиксируют данные по-настоящему.
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


async def _seed(engine: AsyncEngine, schema: str) -> str:
    """Пользователь-админ + продукт с маршрутом: позиция после импорта валидна."""
    async with _durable_session(engine, schema) as db:
        sections: list[Section] = []
        for code, name in (("CUT", "Cut"), ("PACKING", "Pack")):
            section = await db.scalar(select(Section).where(Section.code == code))
            if section is None:
                section = Section(code=code, name=name)
                db.add(section)
            sections.append(section)
        await db.flush()

        route = ProductionRoute(name=f"Route {SKU}", is_active=True)
        db.add(route)
        await db.flush()
        for index, section in enumerate(sections, start=1):
            stage = RouteStage(
                route_id=route.id,
                sequence=index * 10,
                section_id=section.id,
                is_final=index == len(sections),
            )
            db.add(stage)
            await db.flush()
            db.add(
                RouteOperation(
                    route_stage_id=stage.id,
                    sequence=1,
                    operation_name=f"Step {index}",
                )
            )

        product = Product(
            sku=SKU,
            name=f"Product {SKU}",
            type=ProductType.finished_good,
            unit="pcs",
        )
        db.add(product)
        await db.flush()
        product_id = product.id
        # `lengths.append` тянет коллекцию, а после flush атрибут истёк —
        # добавляем строку явным product_id, без ленивой загрузки.
        db.add(ProductLength(product_id=product_id, length_mm=2700, is_primary=True))
        user = User(
            username="commit-287",
            email="commit-287@test.local",
            full_name="Commit 287",
            role=UserRole.admin,
            is_active=True,
        )
        db.add(user)
        email = user.email
        await db.commit()
        # Возвращаем email, а не id: после commit атрибут истёк, и обращение
        # к нему вне await-контекста упало бы MissingGreenlet.
        return email


async def _call_simulate(engine: AsyncEngine, schema: str, *, headers: dict[str, str]) -> object:
    """Вызывает импорт с зависимостью, которая НИЧЕГО не коммитит на выходе."""

    async def override_get_db() -> AsyncIterator[AsyncSession]:
        async with _durable_session(engine, schema) as db:
            yield db

    app.dependency_overrides[get_db] = override_get_db
    try:
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as ac:
            return await ac.post(
                SIMULATE_URL,
                json={
                    "rows": [
                        {
                            "sku": SKU,
                            "name": "Стык 38 мм 2,7",
                            "qty_per_27": 200,
                            "length_m": 2.7,
                            "output_length_m": 2.7,
                            "output_qty": 200,
                            "kind": "ГП",
                        }
                    ]
                },
                headers=headers,
            )
    finally:
        app.dependency_overrides.pop(get_db, None)


async def _read_committed(
    engine: AsyncEngine, schema: str, *, plan_id: int, change_set_id: int
) -> tuple[bool, bool]:
    """Читает с соединения, которое видит только закоммиченное."""
    async with _durable_session(engine, schema) as reader:
        plan = await reader.get(ProductionPlan, plan_id)
        change_set = await reader.get(PlanChangeSet, change_set_id)
    return plan is not None, change_set is not None


@pytest.mark.asyncio
async def test_simulated_import_is_durable_before_response(
    engine: AsyncEngine, module_schema_name: str
) -> None:
    """Импорт плана обязан быть закоммичен ДО ответа.

    Иначе клиент, получивший 201 с `production_plan_id` и сразу пришедший за
    change set / apply, читает незакоммиченное состояние — флейк #287.
    """
    from app.core.security import create_access_token

    email = await _seed(engine, module_schema_name)
    headers = {"Authorization": f"Bearer {create_access_token(subject=email)}"}

    response = await _call_simulate(engine, module_schema_name, headers=headers)
    assert response.status_code == 201, response.text
    payload = response.json()
    plan_id = payload["production_plan_id"]
    change_set_id = payload["change_set_id"]

    plan_visible, change_set_visible = await _read_committed(
        engine,
        module_schema_name,
        plan_id=plan_id,
        change_set_id=change_set_id,
    )
    assert plan_visible, (
        "план не виден из отдельной сессии сразу после 201: коммит случится "
        "только в teardown get_db, уже после ответа — клиент получит 404 в apply (#287)"
    )
    assert change_set_visible, "change set не закоммичен до ответа (#287)"
