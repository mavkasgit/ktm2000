"""Регресс на долговечность импорта плана (#287).

`POST /api/imports/excel/simulate` (и его файловый собрат `/excel`) отдаёт в
ответе `production_plan_id`/`change_set_id`, по которым клиент СРАЗУ бьёт
`POST /api/production-plans/{id}/change-sets/{cid}/apply`. Если эндпоинт не
коммитит сам, коммит делает зависимость `get_db` — а он, по докстрингу
`core/database.py` и по устройству `fastapi.routing.request_response`,
выполняется ПОСЛЕ отправки ответа. Тогда `apply` не находит план и отдаёт 404
«Production plan not found» — ровно тот флейк, что заведён тикетом #287.

Пакет объявляет `Truncation`: код под тестом ходит в базу своим соединением,
и данные обязаны быть реально закоммичены, чтобы отдельная сессия-читатель их
увидела (в транзакции dbcleaner они были бы невидимы по MVCC). Зависимость
подменяется такой, чей teardown делает **rollback**, поэтому выживает ровно
то, что обработчик закоммитил сам.
"""
from __future__ import annotations

from collections.abc import AsyncIterator

import pytest
from app.core.database import get_db
from app.main import app
from app.models.product import Product, ProductLength, ProductType
from app.models.production_plan import PlanChangeSet, ProductionPlan
from app.models.route import ProductionRoute, RouteOperation, RouteStage
from app.models.section import Section
from app.models.user import User, UserRole
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from tests import dbcleaner

SIMULATE_URL = "/api/imports/excel/simulate"
SKU = "ЮП-COMMIT-287"

# Своё соединение у кода под тестом -> изоляция коммитами + TRUNCATE после теста.
DB_STRATEGY = dbcleaner.STRATEGY_TRUNCATION
pytestmark = pytest.mark.usefixtures("cleaner_reset")


async def _seed(cleaner: dbcleaner.Cleaner) -> str:
    """Пользователь-админ + продукт с маршрутом: позиция после импорта валидна."""
    async with cleaner.session() as db:
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


async def _call_simulate(cleaner: dbcleaner.Cleaner, *, headers: dict[str, str]) -> object:
    """Вызывает импорт с зависимостью, которая НИЧЕГО не коммитит на выходе."""

    async def override_get_db() -> AsyncIterator[AsyncSession]:
        async with cleaner.session() as db:
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
    cleaner: dbcleaner.Cleaner, *, plan_id: int, change_set_id: int
) -> tuple[bool, bool]:
    """Читает с соединения, которое видит только закоммиченное."""
    async with cleaner.session() as reader:
        plan = await reader.get(ProductionPlan, plan_id)
        change_set = await reader.get(PlanChangeSet, change_set_id)
    return plan is not None, change_set is not None


@pytest.mark.asyncio
async def test_simulated_import_is_durable_before_response(
    cleaner: dbcleaner.Cleaner,
) -> None:
    """Импорт плана обязан быть закоммичен ДО ответа.

    Иначе клиент, получивший 201 с `production_plan_id` и сразу пришедший за
    change set / apply, читает незакоммиченное состояние — флейк #287.
    """
    from app.core.security import create_access_token

    email = await _seed(cleaner)
    headers = {"Authorization": f"Bearer {create_access_token(subject=email)}"}

    response = await _call_simulate(cleaner, headers=headers)
    assert response.status_code == 201, response.text
    payload = response.json()
    plan_id = payload["production_plan_id"]
    change_set_id = payload["change_set_id"]

    plan_visible, change_set_visible = await _read_committed(
        cleaner,
        plan_id=plan_id,
        change_set_id=change_set_id,
    )
    assert plan_visible, (
        "план не виден из отдельной сессии сразу после 201: коммит случится "
        "только в teardown get_db, уже после ответа — клиент получит 404 в apply (#287)"
    )
    assert change_set_visible, "change set не закоммичен до ответа (#287)"
