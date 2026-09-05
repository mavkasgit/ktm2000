"""Идемпотентность ledger: unique-бэкстоп и 409 на гонку (ADR-0022).

- Сервисный уровень: конкурентные ``record()`` с одним ключом на двух
  реальных соединениях — ровно одна проводка, проигравший получает
  ``StockIdempotencyConflict`` (409).
- Cross-connection replay: повтор с тем же ключом возвращает проводку
  победителя.
- NULL-ключи остаются неидемпотентными (partial unique).
- API double-click: два параллельных POST ``/tasks/{id}/complete`` с одним
  ``idempotency_key`` — исходы {200, 409} или {200, 200-по-replay},
  проводка ровно одна, side effects не задвоены.

Тесты гонки используют отдельные соединения из ``engine`` (общая фикстура
``session`` держит всё на одном соединении — там гонка невоспроизводима).
"""
from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from decimal import Decimal

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy import event, select, text
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker

from app.core.database import get_db
from app.core.security import create_access_token
from app.main import app
from app.stock import (
    Reason,
    StockCommand,
    StockCommandService,
    StockIdempotencyConflict,
    StockTransaction,
)

from tests.stock.test_stock_command import _make_location, _make_product, _make_user
from tests.stock.test_task_completion_transform import (
    _make_transform_setup,
    _receive_input,
    _tx_sum,
)
from tests.test_integrity_invariants import assert_no_stock_ledger_invariants_violations

RACE_KEY = "race-key-1"


@pytest_asyncio.fixture(scope="module", loop_scope="module")
async def _pin_search_path(engine: AsyncEngine, module_schema_name: str):
    """Каждое новое соединение движка сразу получает search_path модуля.

    Engine на NullPool: после любого commit соединение закрывается, и
    следующий запрос уходит на свежее соединение — per-session SET перед
    коммитом недостаточно (сетап трансформации коммитит внутри себя).
    """
    def _set_path(dbapi_conn, _record):
        cur = dbapi_conn.cursor()
        cur.execute(f'SET search_path TO "{module_schema_name}"')
        cur.close()

    event.listen(engine.sync_engine, "connect", _set_path)
    yield
    event.remove(engine.sync_engine, "connect", _set_path)


pytestmark = [pytest.mark.asyncio, pytest.mark.usefixtures("_pin_search_path")]


def _schema_sql(module_schema_name: str) -> str:
    return f'SET search_path TO "{module_schema_name}"'


async def _bump_user_sequence(session: AsyncSession) -> None:
    """Поднимает users-последовательность выше постоянного пола (900k).

    Фикстура ``session`` перезапускает последовательность с 1 на каждый
    тест; закоммиченные этим модулем пользователи не должны занимать
    низкие id — иначе system_user следующего теста упрётся в PK.
    """
    await session.execute(text(
        "SELECT setval(pg_get_serial_sequence('users', 'id'), "
        "GREATEST((SELECT COALESCE(MAX(id), 0) FROM users), 900000) + 1, false)"
    ))


def _auth_headers(fx: dict) -> dict[str, str]:
    """JWT оператора из фикстуры трансформации (subject = email)."""
    return {"Authorization": f"Bearer {create_access_token(subject=fx['user'].email)}"}


# ─── сервисный уровень: гонка на двух соединениях ──────────────────────────


async def test_concurrent_same_key_loser_gets_conflict(
    engine: AsyncEngine, module_schema_name: str,
):
    """Два конкурентных record() с одним ключом: ровно одна проводка,
    проигравший получает StockIdempotencyConflict (409), а не дубль."""
    factory = async_sessionmaker(bind=engine, expire_on_commit=False)
    schema = _schema_sql(module_schema_name)

    async with factory() as setup:
        await setup.execute(text(schema))
        await _bump_user_sequence(setup)
        user = await _make_user(setup, "idem-race")
        product = await _make_product(setup, "IDEM-RACE")
        raw = await _make_location(setup, code="IDEMRAW", name="IdemRaw", loc_type="raw_stock")
        laser = await _make_location(setup, code="IDEMLASER", name="IdemLaser", loc_type="laser")
        await StockCommandService().record(setup, StockCommand(
            product_id=product.id,
            to_location_id=raw.id,
            quantity=Decimal("100"),
            reason=Reason.MANUAL_IN,
            created_by=user.id,
        ))
        await setup.commit()

    cmd = StockCommand(
        product_id=product.id,
        from_location_id=raw.id,
        to_location_id=laser.id,
        quantity=Decimal("10"),
        reason=Reason.TRANSFER_RECEIVE,
        created_by=user.id,
        idempotency_key=RACE_KEY,
    )
    svc = StockCommandService()

    async with factory() as winner:
        await winner.execute(text(schema))
        first = await svc.record(winner, cmd)  # INSERT прошёл, НЕ закоммичен

        async with factory() as loser:
            await loser.execute(text(schema))
            task = asyncio.create_task(svc.record(loser, cmd))
            # Проигравший проходит replay-SELECT (пусто: INSERT победителя
            # ещё не закоммичен) и зависает на flush — ждёт исхода победителя.
            await asyncio.sleep(0.5)
            await winner.commit()
            with pytest.raises(StockIdempotencyConflict):
                await task

    async with factory() as check:
        await check.execute(text(schema))
        rows = (
            await check.execute(
                select(StockTransaction).where(StockTransaction.idempotency_key == RACE_KEY)
            )
        ).scalars().all()
        await assert_no_stock_ledger_invariants_violations(check, context="idem race")

    assert len(rows) == 1, "гонка не должна создавать дубликаты проводок"
    assert rows[0].id == first.id


async def test_replay_across_connections_returns_prior(
    engine: AsyncEngine, module_schema_name: str,
):
    """Повтор операции с тем же ключом на новом соединении (реальный retry
    клиента после 409/таймаута) возвращает проводку победителя."""
    factory = async_sessionmaker(bind=engine, expire_on_commit=False)
    schema = _schema_sql(module_schema_name)

    async with factory() as setup:
        await setup.execute(text(schema))
        await _bump_user_sequence(setup)
        user = await _make_user(setup, "idem-retry")
        product = await _make_product(setup, "IDEM-RETRY")
        raw = await _make_location(setup, code="IDEMRAW2", name="IdemRaw", loc_type="raw_stock")
        laser = await _make_location(setup, code="IDEMLASER2", name="IdemLaser", loc_type="laser")
        await StockCommandService().record(setup, StockCommand(
            product_id=product.id,
            to_location_id=raw.id,
            quantity=Decimal("100"),
            reason=Reason.MANUAL_IN,
            created_by=user.id,
        ))
        await setup.commit()

    cmd = StockCommand(
        product_id=product.id,
        from_location_id=raw.id,
        to_location_id=laser.id,
        quantity=Decimal("10"),
        reason=Reason.TRANSFER_RECEIVE,
        created_by=user.id,
        idempotency_key="retry-key-1",
    )
    svc = StockCommandService()

    async with factory() as first_conn:
        await first_conn.execute(text(schema))
        first = await svc.record(first_conn, cmd)
        await first_conn.commit()

    async with factory() as retry_conn:
        await retry_conn.execute(text(schema))
        replayed = await svc.record(retry_conn, cmd)

    assert replayed.id == first.id


async def test_null_idempotency_key_is_not_idempotent(session: AsyncSession):
    """Partial unique: записи без ключа не конфликтуют — их сколько угодно."""
    user = await _make_user(session)
    product = await _make_product(session)
    raw = await _make_location(session, code="IDEMNULLR", name="Raw", loc_type="raw_stock")
    laser = await _make_location(session, code="IDEMNULLL", name="Laser", loc_type="laser")

    svc = StockCommandService()
    await svc.record(session, StockCommand(
        product_id=product.id,
        to_location_id=raw.id,
        quantity=Decimal("50"),
        reason=Reason.MANUAL_IN,
        created_by=user.id,
    ))
    for _ in range(2):
        await svc.record(session, StockCommand(
            product_id=product.id,
            from_location_id=raw.id,
            to_location_id=laser.id,
            quantity=Decimal("5"),
            reason=Reason.TRANSFER_RECEIVE,
            created_by=user.id,
            idempotency_key=None,
        ))
    await session.commit()

    # Две безключевые передачи по одному продукту — обе записаны
    # (partial unique не конфликтует на NULL-ключах). MANUAL_IN сетапа
    # в подсчёт не входит.
    count = await session.execute(
        select(StockTransaction).where(
            StockTransaction.product_id == product.id,
            StockTransaction.reason == Reason.TRANSFER_RECEIVE,
        )
    )
    assert len(count.scalars().all()) == 2


# ─── API double-click: два параллельных POST с одним ключом ────────────────


@pytest_asyncio.fixture
async def isolated_client(
    engine: AsyncEngine, module_schema_name: str,
) -> AsyncIterator[AsyncClient]:
    """API-клиент, где каждый запрос получает СВОЁ соединение из engine.

    Общая фикстура ``client`` подсовывает всем запросам один session —
    параллельный double-click через неё невоспроизводим.
    """
    factory = async_sessionmaker(bind=engine, expire_on_commit=False)

    async def override_get_db() -> AsyncIterator[AsyncSession]:
        async with factory() as db:
            await db.execute(text(_schema_sql(module_schema_name)))
            try:
                yield db
                await db.commit()
            except Exception:
                await db.rollback()
                raise

    app.dependency_overrides[get_db] = override_get_db
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac
    app.dependency_overrides.clear()


async def test_api_double_click_complete_records_single_movement(
    isolated_client: AsyncClient, engine: AsyncEngine, module_schema_name: str,
):
    """Double-click «Завершить»: {200, 409} или {200, 200-по-replay},
    но проводка списания ровно одна и инварианты ledger целы."""
    factory = async_sessionmaker(bind=engine, expire_on_commit=False)
    schema = _schema_sql(module_schema_name)

    async with factory() as setup:
        await setup.execute(text(schema))
        await _bump_user_sequence(setup)
        fx = await _make_transform_setup(setup, sku="IDEM-API")
        await _receive_input(setup, fx, quantity=Decimal("80"))
        await setup.commit()

    url = f"/api/shopfloor/tasks/{fx['task'].id}/complete"
    payload = {"good_quantity": "80", "defect_quantity": "0", "idempotency_key": "dblclick-1"}
    headers = _auth_headers(fx)

    r1, r2 = await asyncio.gather(
        isolated_client.post(url, json=payload, headers=headers),
        isolated_client.post(url, json=payload, headers=headers),
    )

    for resp in (r1, r2):
        assert resp.status_code in (200, 409), resp.text
        if resp.status_code == 409:
            assert resp.json()["error_code"] == "stock_idempotency_conflict"
    assert 200 in (r1.status_code, r2.status_code), "хотя бы одна подача проходит"

    async with factory() as check:
        await check.execute(text(schema))
        consumed = await _tx_sum(
            check, fx["task"].id, Reason.TRANSFORM_CONSUME, any_dims=True,
        )
        await assert_no_stock_ledger_invariants_violations(check, context="double-click")

    assert consumed == Decimal("80"), "double-click не должен задваивать списание"
