"""Гонка двух выдач и свежесть баланса (``execute_issue``).

Сессия-вызыватель (HTTP-слой) читает остатки ДО выдачи, и та же сессия
используется внутри ``execute_issue`` — поэтому проверка строится на
реальных соединениях из ``engine`` (общая фикстура ``session`` держит всё
на одном соединении и на savepoint-транзакции, невидимой конкуренту):

- две параллельные выдачи одного склада: суммарно склад не вычерпан;
- параллельное списание с внешнего соединения: выдача обязана увидеть
  фактический остаток, а не копию из identity map;
- замок покрывает ВСЕ строки баланса ключа (в т.ч. невидимые подбору
  отрицательные строки), а не только кандидатов предыдущей выборки.

Сетап коммитится на отдельном соединении (модульный паттерн
``test_ledger_idempotency``), поэтому данные видны всем участникам гонки.
"""
from __future__ import annotations

import asyncio
from datetime import UTC, datetime
from decimal import Decimal

import pytest
import pytest_asyncio
from app.domain.shortage import ShortageStrategy
from app.models.product import Product, ProductType
from app.models.production_plan import PlanPosition
from app.models.section import Section
from app.stock.models import QualityState, Reason, StockBalance
from app.stock.services import StockCommand, StockCommandService
from app.transfers.issue_service import execute_issue
from sqlalchemy import event, select, text
from sqlalchemy.exc import DBAPIError
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker

from tests import dbcleaner
from tests.helpers.completed_operations import build_operation_route
from tests.test_integrity_invariants import assert_no_stock_ledger_invariants_violations

STAGES = [
    ("Склад-заготовка", "raw_stock", ["STORE"]),
    ("Цех-раскрой", "production", ["CUT"]),
    ("Цех-сверло", "production", ["DRILL"]),
]
DIMS = {"length_mm": 2750}
OPS = ["STORE"]

# Гонки идут на своих соединениях из engine -> коммиты видны конкурентам,
# поэтому изоляция — коммитами + TRUNCATE после теста (канон tests/AGENTS.md).
DB_STRATEGY = dbcleaner.STRATEGY_TRUNCATION
pytestmark = pytest.mark.usefixtures("_pin_search_path")


@pytest_asyncio.fixture(scope="module", loop_scope="module")
async def _pin_search_path(engine: AsyncEngine, module_schema_name: str):
    """Каждое новое соединение движка сразу получает search_path модуля.

    Engine на NullPool: после любого commit соединение закрывается, и
    следующий запрос уходит на свежее соединение — per-session SET перед
    коммитом недостаточно (сетап коммитит внутри себя).
    """
    def _set_path(dbapi_conn, _record):
        cur = dbapi_conn.cursor()
        cur.execute(f'SET search_path TO "{module_schema_name}"')
        cur.close()

    event.listen(engine.sync_engine, "connect", _set_path)
    yield
    event.remove(engine.sync_engine, "connect", _set_path)


async def _bump_user_sequence(session: AsyncSession) -> None:
    """Коммитимые модулем пользователи не должны занимать низкие id."""
    await session.execute(text(
        "SELECT setval(pg_get_serial_sequence('users', 'id'), "
        "GREATEST((SELECT COALESCE(MAX(id), 0) FROM users), 900000) + 1, false)"
    ))


async def _setup_warehouse(engine: AsyncEngine, *, sku: str, stock_qty: Decimal) -> dict:
    """Коммит-сетап: маршрут склад→цехи, позиция 2,75 м, приход на склад.

    Возвращает плоские id (объекты после commit не нужны) — каждая
    сессия-участник перезагружает позицию у себя.
    """
    factory = async_sessionmaker(bind=engine, expire_on_commit=False)
    async with factory() as db:
        await _bump_user_sequence(db)
        fx = await build_operation_route(db, sku=sku, stages=STAGES, input_dimensions=DIMS)
        await StockCommandService().record(db, StockCommand(
            product_id=fx["product"].id,
            to_location_id=fx["sections"][0].id,
            quantity=stock_qty,
            reason=Reason.MANUAL_IN,
            dimensions=DIMS,
            completed_operations=OPS,
            created_by=fx["user"].id,
        ))
        await db.commit()
        return {
            "position_id": fx["position"].id,
            "product_id": fx["product"].id,
            "stock_location_id": fx["sections"][0].id,
            "user_id": fx["user"].id,
        }


async def _setup_group_warehouse(
    engine: AsyncEngine,
    *,
    sku: str,
    equivalent_sku: str,
    stock_qty: Decimal,
) -> dict:
    """Коммит-сетап группы: маршрут и позиция на A, вся куча лежит под B.

    ``SETVAL`` поднимает последовательность пользователей, чтобы коммитимая
    фикстура не занимала низкие id. Возвращает плоские id: позиция,
    артикул задания (A), фактический SKU кучи (B).
    """
    factory = async_sessionmaker(bind=engine, expire_on_commit=False)
    async with factory() as db:
        await _bump_user_sequence(db)
        fx = await build_operation_route(db, sku=sku, stages=STAGES, input_dimensions=DIMS)
        equivalent = Product(
            sku=equivalent_sku,
            name=equivalent_sku,
            type=ProductType.component,
            unit="pcs",
            is_active=True,
        )
        db.add(equivalent)
        await db.flush()
        fx["product"].aliases = [equivalent_sku]
        await StockCommandService().record(db, StockCommand(
            product_id=equivalent.id,
            to_location_id=fx["sections"][0].id,
            quantity=stock_qty,
            reason=Reason.MANUAL_IN,
            dimensions=DIMS,
            completed_operations=OPS,
            created_by=fx["user"].id,
        ))
        await db.commit()
        return {
            "position_id": fx["position"].id,
            "task_product_id": fx["product"].id,
            "equivalent_product_id": equivalent.id,
            "stock_location_id": fx["sections"][0].id,
            "user_id": fx["user"].id,
        }


async def test_parallel_execute_issue_cannot_overdraw_stock(engine: AsyncEngine):
    """Две одновременные выдачи по 60 из склада на 100: суммарно — 100.

    Без лока и перечитывания остатка вторая выдача считает план по
    устаревшей копии склада и вычерпывает его второй раз: ledger уходит в
    минус, «взято» 120 при 100 доступных.
    """
    factory = async_sessionmaker(bind=engine, expire_on_commit=False)
    ids = await _setup_warehouse(engine, sku="RACE-PAR", stock_qty=Decimal(100))

    async def _issue_b() -> dict:
        async with factory() as db_b:
            position = await db_b.get(PlanPosition, ids["position_id"])
            res = await execute_issue(
                db_b,
                position=position,
                product_id=ids["product_id"],
                required=Decimal(60),
                actor_id=ids["user_id"],
                idempotency_key="race-parallel-B",
                shortage_strategy=ShortageStrategy.partial,
            )
            await db_b.commit()
            return res

    async with factory() as db_a:
        position_a = await db_a.get(PlanPosition, ids["position_id"])
        res_a = await execute_issue(
            db_a,
            position=position_a,
            product_id=ids["product_id"],
            required=Decimal(60),
            actor_id=ids["user_id"],
            idempotency_key="race-parallel-A",
            shortage_strategy=ShortageStrategy.partial,
        )
        task_b = asyncio.create_task(_issue_b())
        # B успевает прочесть склад (100) и упирается в замок A; коммит A
        # разблокирует её — и она обязана увидеть фактические 40, а не свой
        # прочитанный ранее остаток.
        await asyncio.sleep(0.5)
        await db_a.commit()
        res_b = await task_b

    assert res_a["collected"] == Decimal(60)
    assert res_a["collected"] + res_b["collected"] == Decimal(100), (
        "суммарная выдача не может превышать фактический склад"
    )
    assert res_b["deficit"] == Decimal(20)

    async with factory() as check:
        qty = await check.scalar(
            select(StockBalance.balance_qty).where(
                StockBalance.product_id == ids["product_id"],
                StockBalance.location_id == ids["stock_location_id"],
            )
        )
        assert qty is None or qty >= 0, "при корректном локале склад не уходит в минус"
        await assert_no_stock_ledger_invariants_violations(check, context="parallel issue")


async def test_execute_issue_sees_concurrent_write_not_identity_map(engine: AsyncEngine):
    """Списание с внешнего соединения после прочтения — выдача берёт факт.

    Та же сессия уже держит строку баланса в identity map; обычный SELECT
    внутри ``execute_issue`` её не обновляет. Без принудительного refresh
    «пересчёт» плана посчитал бы по устаревшим 100 и вычерпал склад,
    которого уже нет.
    """
    factory = async_sessionmaker(bind=engine, expire_on_commit=False)
    ids = await _setup_warehouse(engine, sku="RACE-STALE", stock_qty=Decimal(100))

    async with factory() as db_caller:
        position = await db_caller.get(PlanPosition, ids["position_id"])
        stale = await db_caller.scalar(
            select(StockBalance).where(
                StockBalance.product_id == ids["product_id"],
                StockBalance.location_id == ids["stock_location_id"],
            )
        )
        assert stale is not None and stale.balance_qty == Decimal(100)

        async with factory() as db_other:
            await StockCommandService().record(db_other, StockCommand(
                product_id=ids["product_id"],
                from_location_id=ids["stock_location_id"],
                quantity=Decimal(80),
                reason=Reason.MANUAL_OUT,
                dimensions=DIMS,
                completed_operations=OPS,
                created_by=ids["user_id"],
            ))
            await db_other.commit()

        # Премиса staleness: объект в сессии вызывающего остаётся старым —
        # именно на нём молча считается «пересчёт» без populate_existing.
        assert stale.balance_qty == Decimal(100)

        res = await execute_issue(
            db_caller,
            position=position,
            product_id=ids["product_id"],
            required=Decimal(60),
            actor_id=ids["user_id"],
            idempotency_key="race-stale-1",
            shortage_strategy=ShortageStrategy.partial,
        )
        await db_caller.commit()

    assert res["collected"] == Decimal(20), "взято ровно столько, сколько реально осталось"
    assert res["deficit"] == Decimal(40)

    async with factory() as check:
        qty = await check.scalar(
            select(StockBalance.balance_qty).where(
                StockBalance.product_id == ids["product_id"],
                StockBalance.location_id == ids["stock_location_id"],
            )
        )
        assert qty is None or qty >= 0
        await assert_no_stock_ledger_invariants_violations(check, context="stale issue")


async def test_lock_covers_whole_key_including_negative_rows(engine: AsyncEngine):
    """Замок — по всему ключу «артикул × склады», включая невидимые строки.

    Отрицательная строка склада подбору не видна (``balance_qty > 0``), но
    параллельная приёмка может наполнить её — и тогда её вычерпают без
    лока. Проверяем без таймингов: пока выдача A не закоммичена, второе
    соединение не может залочить даже минусовую строку (NOWAIT падает).
    """
    factory = async_sessionmaker(bind=engine, expire_on_commit=False)
    ids = await _setup_warehouse(engine, sku="RACE-LOCK", stock_qty=Decimal(100))

    async with factory() as setup:
        shadow = Section(
            code="RACE-LOCK-W", name="Склад-тень", type="wip_stock",
            is_active=True, sort_order=95,
        )
        setup.add(shadow)
        await setup.flush()
        setup.add(StockBalance(
            product_id=ids["product_id"],
            location_id=shadow.id,
            quality_state=QualityState.GOOD,
            dimensions=DIMS,
            completed_operations=OPS,
            balance_qty=Decimal(-30),  # минус после negative_remainder
            refreshed_at=datetime.now(UTC),
        ))
        await setup.commit()
        shadow_id = shadow.id

    async with factory() as lookup:
        neg_balance_id = await lookup.scalar(
            select(StockBalance.id).where(
                StockBalance.location_id == shadow_id,
                StockBalance.product_id == ids["product_id"],
            )
        )
    assert neg_balance_id is not None

    async with factory() as db_a:
        position = await db_a.get(PlanPosition, ids["position_id"])
        res_a = await execute_issue(
            db_a,
            position=position,
            product_id=ids["product_id"],
            required=Decimal(60),
            actor_id=ids["user_id"],
            idempotency_key="race-lock-A",
            shortage_strategy=ShortageStrategy.partial,
        )
        assert res_a["collected"] == Decimal(60)

        async with factory() as db_probe:
            # Минусовая строка лежит в замке выдачи (она входит в ключ
            # «артикул × склады»), хотя подбора не касалась: NOWAIT обязан
            # упасть.
            with pytest.raises(DBAPIError):
                await db_probe.execute(
                    text("SELECT id FROM stock_balances WHERE id = :x FOR UPDATE NOWAIT"),
                    {"x": neg_balance_id},
                )
        # Тестирующая выдача не коммитится — остальной модуль стартует с
        # чистого склада.
        await db_a.rollback()


async def test_parallel_issue_on_group_members_cannot_overdraw_one_pile(
    engine: AsyncEngine,
):
    """Позиции на A и B делят кучу: групповой замок не даёт вычерпать её дважды.

    Остаток лежит под B (эквивалент A). Без ``product_id.in_(group_ids)``
    выдача на A не залочила бы ни одной строки, обе выдачи прочли бы 100 и
    списали по 60 — 120 из 100.
    """
    factory = async_sessionmaker(bind=engine, expire_on_commit=False)
    ids = await _setup_group_warehouse(
        engine,
        sku="RACE-GRP-A",
        equivalent_sku="RACE-GRP-B",
        stock_qty=Decimal(100),
    )

    async def _issue_b() -> dict:
        async with factory() as db_b:
            position = await db_b.get(PlanPosition, ids["position_id"])
            res = await execute_issue(
                db_b,
                position=position,
                product_id=ids["equivalent_product_id"],
                required=Decimal(60),
                actor_id=ids["user_id"],
                idempotency_key="race-group-B",
                shortage_strategy=ShortageStrategy.partial,
            )
            await db_b.commit()
            return res

    async with factory() as db_a:
        position_a = await db_a.get(PlanPosition, ids["position_id"])
        res_a = await execute_issue(
            db_a,
            position=position_a,
            product_id=ids["task_product_id"],
            required=Decimal(60),
            actor_id=ids["user_id"],
            idempotency_key="race-group-A",
            shortage_strategy=ShortageStrategy.partial,
        )
        task_b = asyncio.create_task(_issue_b())
        # B читает кучу до коммита A и обязана упереться в групповой замок:
        # после коммита она увидит фактический остаток, а не свои 100.
        await asyncio.sleep(0.5)
        await db_a.commit()
        res_b = await task_b

    assert res_a["collected"] == Decimal(60)
    assert res_a["collected"] + res_b["collected"] == Decimal(100), (
        "две выдачи на разные SKU одной группы не могут вычерпать кучу дважды"
    )
    assert res_b["deficit"] == Decimal(20)

    async with factory() as check:
        qty = await check.scalar(
            select(StockBalance.balance_qty).where(
                StockBalance.product_id == ids["equivalent_product_id"],
                StockBalance.location_id == ids["stock_location_id"],
            )
        )
        assert qty is None or qty >= 0
