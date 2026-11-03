"""Контракт [`dbcleaner.py`](dbcleaner.py): guard и стратегии отката.

`Transaction` проверяется ещё и `test_hybrid_db_isolation.py`; здесь —
остальные стратегии и то, что коммитящая чистка не запускается на чужой
базе. Каждый тест держит **свою** схему: `TRUNCATE` не должен задевать
данные соседних тестов модуля.
"""
from __future__ import annotations

import uuid
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

import pytest
import pytest_asyncio
from app.models.product import Product, ProductLength, ProductType
from app.models.section import Section
from sqlalchemy import func, select
from sqlalchemy.engine import URL

from tests import dbcleaner
from tests.conftest import baseline_setup


@asynccontextmanager
async def _cleaner(url: URL, strategy: str) -> AsyncIterator[dbcleaner.Cleaner]:
    """Cleaner со своей схемой: базовая линия та же, что у пакета."""
    schema = f"t_{uuid.uuid4().hex[:8]}"
    test_cleaner = dbcleaner.Cleaner(
        url,
        schema,
        setup=baseline_setup,
        strategy=strategy,
        drop_schema=True,
    )
    await test_cleaner.start()
    try:
        yield test_cleaner
    finally:
        await test_cleaner.stop()


@pytest_asyncio.fixture
async def truncation_cleaner(base_test_db_url: URL) -> AsyncIterator[dbcleaner.Cleaner]:
    async with _cleaner(base_test_db_url, dbcleaner.STRATEGY_TRUNCATION) as cleaner:
        yield cleaner


@pytest_asyncio.fixture
async def deletion_cleaner(base_test_db_url: URL) -> AsyncIterator[dbcleaner.Cleaner]:
    async with _cleaner(base_test_db_url, dbcleaner.STRATEGY_DELETION) as cleaner:
        yield cleaner


@pytest_asyncio.fixture
async def null_cleaner(base_test_db_url: URL) -> AsyncIterator[dbcleaner.Cleaner]:
    async with _cleaner(base_test_db_url, dbcleaner.STRATEGY_NULL) as cleaner:
        yield cleaner


def _with_database(url: URL, database: str) -> URL:
    return url.set(database=database)


# ─── guard: коммитящая стратегия не запускается на чужой базе ──────────────


@pytest.mark.parametrize("strategy", sorted(dbcleaner.COMMITTING_STRATEGIES))
@pytest.mark.parametrize("database", ["ktm2000_dev", "app", "production"])
def test_committing_strategy_refuses_database_without_marker(
    base_test_db_url: URL, strategy: str, database: str
) -> None:
    """Имя без `test`/`e2e`/`scratch` — промах DSN, а не повод вычистить базу."""
    with pytest.raises(RuntimeError, match="must contain one of"):
        dbcleaner.Cleaner(
            _with_database(base_test_db_url, database),
            "t_deadbeef",
            setup=baseline_setup,
            strategy=strategy,
        )


@pytest.mark.parametrize("strategy", sorted(dbcleaner.COMMITTING_STRATEGIES))
@pytest.mark.parametrize("database", ["ktm2000_test", "app_e2e", "scratch_pad"])
def test_committing_strategy_accepts_marked_database(
    base_test_db_url: URL, strategy: str, database: str
) -> None:
    cleaner = dbcleaner.Cleaner(
        _with_database(base_test_db_url, database),
        "t_deadbeef",
        setup=baseline_setup,
        strategy=strategy,
    )
    assert cleaner.strategy == strategy


@pytest.mark.parametrize("database", ["ktm2000_dev", "app"])
def test_transaction_strategy_is_not_guarded(base_test_db_url: URL, database: str) -> None:
    """`Transaction` ничего не стирает — ей имя базы безразлично."""
    cleaner = dbcleaner.Cleaner(
        _with_database(base_test_db_url, database),
        "t_deadbeef",
        setup=baseline_setup,
        strategy=dbcleaner.STRATEGY_TRANSACTION,
    )
    assert cleaner.strategy == dbcleaner.STRATEGY_TRANSACTION


def test_unknown_strategy_is_rejected(base_test_db_url: URL) -> None:
    with pytest.raises(ValueError, match="Unknown cleaner strategy"):
        dbcleaner.Cleaner(
            base_test_db_url,
            "t_deadbeef",
            setup=baseline_setup,
            strategy="truncate-please",
        )


# ─── Truncation: данные и последовательности возвращаются к базовой линии ──


@pytest.mark.asyncio
async def test_truncation_resets_rows_and_identity(
    truncation_cleaner: dbcleaner.Cleaner,
) -> None:
    """После `reset()` нет строк, а identity снова с 1 — как у голой схемы."""
    async with truncation_cleaner.session() as db:
        first = Section(code="DBCLEAN-TRUNC-1", name="Trunc 1")
        second = Section(code="DBCLEAN-TRUNC-2", name="Trunc 2")
        db.add_all([first, second])
        await db.commit()
        assert (first.id, second.id) == (1, 2)

    await truncation_cleaner.reset()

    async with truncation_cleaner.session() as db:
        assert await db.scalar(select(func.count()).select_from(Section)) == 0
        fresh = Section(code="DBCLEAN-TRUNC-3", name="Trunc 3")
        db.add(fresh)
        await db.commit()
        # RESTART IDENTITY: последовательность пошла заново, id == 1.
        assert fresh.id == 1


# ─── Deletion: дети удаляются раньше родителей ─────────────────────────────


@pytest.mark.asyncio
async def test_deletion_removes_children_before_parents(
    deletion_cleaner: dbcleaner.Cleaner,
) -> None:
    """`DELETE` идёт от детей к родителям — иначе FK не дал бы удалить."""
    async with deletion_cleaner.session() as db:
        product = Product(sku="DBCLEAN-DEL", name="Del", type=ProductType.finished_good)
        db.add(product)
        await db.flush()
        product_id = product.id
        db.add(ProductLength(product_id=product_id, length_mm=1000, is_primary=True))
        await db.commit()

    await deletion_cleaner.reset()

    async with deletion_cleaner.session() as db:
        assert await db.scalar(select(func.count()).select_from(Product)) == 0
        assert await db.scalar(select(func.count()).select_from(ProductLength)) == 0


# ─── Null: чистки нет, данные живут до конца пакета ────────────────────────


@pytest.mark.asyncio
async def test_null_strategy_leaves_data_in_place(null_cleaner: dbcleaner.Cleaner) -> None:
    async with null_cleaner.session() as db:
        db.add(Section(code="DBCLEAN-NULL", name="Null"))
        await db.commit()

    await null_cleaner.reset()

    async with null_cleaner.session() as db:
        assert await db.scalar(select(func.count()).select_from(Section)) == 1
