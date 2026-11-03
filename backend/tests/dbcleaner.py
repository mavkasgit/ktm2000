"""Порт `dbcleaner <https://github.com/mokevnin/dbcleaner>`_ для pytest.

Го-библиотека решает одну задачу: вернуть базу к базовой линии после теста и
выбрать, **как** это сделать. Здесь то же самое, один в один по смыслу:

* **Transaction** (по умолчанию) — весь тест идёт в одной транзакции, которая
  откатывается по завершении. `commit()` внутри кода под тестом отпускает
  SAVEPOINT, а не фиксирует данные, поэтому вложенные транзакции приложения
  работают. Годится всегда, когда тест пользуется выданной сессией.
* **Truncation** — после теста `TRUNCATE ... RESTART IDENTITY CASCADE`.
  Нужна пакетам, чей код ходит в базу **своим соединением**: тогда данные
  должны быть реально закоммичены, чтобы их увидел другой коннект.
* **Deletion** — после теста `DELETE` от детей к родителям. Для случаев, где
  `TRUNCATE` недоступен (нет привилегии) или таблиц мало.
* **Null** — не чистим ничего: тест сам управляет данными (например, срез
  фикстуры, закоммиченный один раз на модуль).

Один `Cleaner` — на тестовый пакет (здесь: на модуль). Он же владеет базовой
линией (`setup`: миграции/`create_all`, триггеры, справочники) и выдаёт
сессии через `session()` — аналог `cleaner.DB(t)`.

Отличие от Го-версии только в том, что «своя база на процесс» у нас выражена
схемой: run-DB выдаёт launcher (`scripts/test-run.ps1`), а `Cleaner` держит
свою схему `t_<uuid8>` с `search_path` на уровне соединения — это аналог
`WithTemplate`, поэтому `-p 1` (в pytest — принудительная сериализация) не
нужен: `--dist loadfile` разводит модули по воркерам.
"""

from __future__ import annotations

import logging
from collections.abc import AsyncIterator, Awaitable, Callable
from contextlib import asynccontextmanager

from sqlalchemy import Table, text
from sqlalchemy.engine import URL, make_url
from sqlalchemy.ext.asyncio import (
    AsyncConnection,
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.pool import NullPool

logger = logging.getLogger(__name__)

#: Стратегии отката — те же имена, что в dbcleaner.
STRATEGY_TRANSACTION = "transaction"
STRATEGY_TRUNCATION = "truncation"
STRATEGY_DELETION = "deletion"
STRATEGY_NULL = "null"

#: Коммитящие стратегии стирают базу целиком, поэтому имя базы обязано
#: содержать один из маркеров — иначе промах DSN вычистит dev-базу.
GUARD_MARKERS = ("test", "e2e", "scratch")

COMMITTING_STRATEGIES = frozenset({STRATEGY_TRUNCATION, STRATEGY_DELETION})

Setup = Callable[[AsyncConnection], Awaitable[None]]


def _default_guard(database_name: str) -> bool:
    """Имя базы похоже на тестовую? (аналог `WithGuard` по умолчанию)."""
    lowered = (database_name or "").lower()
    return any(marker in lowered for marker in GUARD_MARKERS)


def _quote_ident(name: str) -> str:
    return '"' + name.replace('"', '""') + '"'


class Cleaner:
    """Одна база-песочница на тестовый пакет.

    :param url: DSN run-базы (её выдаёт launcher).
    :param schema: схема пакета — «своя база на процесс».
    :param setup: базовая линия: выполняется один раз, коммитится.
    :param strategy: как откатывать тест; по умолчанию ``transaction``.
    :param guard: проверка имени базы для коммитящих стратегий.
    :param drop_schema: дропнуть схему в `stop()` (ручной режим на общей
        статичной базе; в launcher-режиме run-DB падает целиком).
    """

    def __init__(
        self,
        url: str | URL,
        schema: str,
        *,
        setup: Setup,
        strategy: str = STRATEGY_TRANSACTION,
        guard: Callable[[str], bool] | None = None,
        drop_schema: bool = False,
    ) -> None:
        if strategy not in {
            STRATEGY_TRANSACTION,
            STRATEGY_TRUNCATION,
            STRATEGY_DELETION,
            STRATEGY_NULL,
        }:
            raise ValueError(f"Unknown cleaner strategy: {strategy!r}")

        self._url = url if isinstance(url, URL) else make_url(url)
        self._schema = schema
        self._setup = setup
        self._strategy = strategy
        self._guard = guard or _default_guard
        self._drop_schema = drop_schema
        self._engine: AsyncEngine | None = None

        if strategy in COMMITTING_STRATEGIES:
            database_name = self._url.database or ""
            if not self._guard(database_name):
                raise RuntimeError(
                    f"Refusing {strategy!r} cleanup on database {database_name!r}: "
                    f"the name must contain one of {GUARD_MARKERS}. "
                    "Point TEST_DATABASE_URL at a test database instead of "
                    "loosening the guard."
                )

    # ── свойства ────────────────────────────────────────────────────────

    @property
    def strategy(self) -> str:
        return self._strategy

    @property
    def schema(self) -> str:
        return self._schema

    @property
    def engine(self) -> AsyncEngine:
        if self._engine is None:
            raise RuntimeError("Cleaner is not started: call `await cleaner.start()`.")
        return self._engine

    def url(self) -> str:
        """DSN для кода, который открывает соединения сам."""
        return self._url.render_as_string(hide_password=False)

    # ── жизненный цикл ──────────────────────────────────────────────────

    async def start(self) -> Cleaner:
        """Создать схему пакета и прогнать базовую линию (`WithSetup`)."""
        self._engine = create_async_engine(
            self._url.render_as_string(hide_password=False),
            poolclass=NullPool,
            # `search_path` на уровне соединения, а не `SET` внутри
            # транзакции: `SET` откатывается вместе с тестом, а код под
            # тестом коммитит и получает новое соединение (NullPool).
            connect_args={"server_settings": {"search_path": self._schema}},
        )
        async with self.engine.begin() as conn:
            await conn.execute(
                text(f"CREATE SCHEMA IF NOT EXISTS {_quote_ident(self._schema)}")
            )
            await self._setup(conn)
        return self

    async def stop(self) -> None:
        if self._engine is None:
            return
        try:
            if self._drop_schema:
                try:
                    async with self._engine.begin() as conn:
                        await conn.execute(
                            text(
                                f"DROP SCHEMA IF EXISTS {_quote_ident(self._schema)} CASCADE"
                            )
                        )
                except Exception:
                    logger.debug("Failed to drop schema %s", self._schema, exc_info=True)
        finally:
            await self._engine.dispose()
            self._engine = None

    # ── выдача сессии: аналог cleaner.DB(t) ─────────────────────────────

    @asynccontextmanager
    async def session(
        self, *, session_cls: type[AsyncSession] = AsyncSession
    ) -> AsyncIterator[AsyncSession]:
        """Сессия на базовой линии; изоляция — по стратегии пакета."""
        if self._strategy == STRATEGY_TRANSACTION:
            async with self._transactional_session(session_cls) as db:
                yield db
        else:
            async with self._plain_session(session_cls) as db:
                yield db

    @asynccontextmanager
    async def _transactional_session(
        self, session_cls: type[AsyncSession]
    ) -> AsyncIterator[AsyncSession]:
        async with self.engine.connect() as conn:
            transaction = await conn.begin()
            factory = async_sessionmaker(
                bind=conn,
                class_=session_cls,
                expire_on_commit=False,
                # `commit()` кода под тестом становится SAVEPOINT и не может
                # зафиксировать данные — тест всё равно откатится целиком.
                join_transaction_mode="create_savepoint",
            )
            async with factory() as db:
                try:
                    yield db
                finally:
                    await db.rollback()
                    await transaction.rollback()

    @asynccontextmanager
    async def _plain_session(
        self, session_cls: type[AsyncSession]
    ) -> AsyncIterator[AsyncSession]:
        factory = async_sessionmaker(
            bind=self.engine, class_=session_cls, expire_on_commit=False
        )
        # Закрытие (а не явный `rollback`) — объекты остаются пригодными для
        # чтения после выхода: тесты сравнивают `row.id` уже вне сессии.
        async with factory() as db:
            yield db

    # ── откат: `cleaner.Clean` ──────────────────────────────────────────

    async def reset(self) -> None:
        """Вернуть базу к базовой линии (no-op для транзакции и `null`)."""
        if self._strategy == STRATEGY_TRUNCATION:
            await self._truncate()
        elif self._strategy == STRATEGY_DELETION:
            await self._delete()

    def _sorted_tables(self) -> list[Table]:
        # Ленивый импорт: модуль не тянет модели при импорте тестов.
        from app.models.base import Base

        return list(Base.metadata.sorted_tables)

    async def _truncate(self) -> None:
        tables = self._sorted_tables()
        if not tables:
            return
        names = ", ".join(_quote_ident(table.name) for table in tables)
        async with self.engine.begin() as conn:
            await conn.execute(
                text(f"TRUNCATE TABLE {names} RESTART IDENTITY CASCADE")
            )

    async def _delete(self) -> None:
        async with self.engine.begin() as conn:
            # `sorted_tables` — от родителей к детям, удаляем наоборот.
            for table in reversed(self._sorted_tables()):
                await conn.execute(text(f"DELETE FROM {_quote_ident(table.name)}"))

    def __repr__(self) -> str:  # pragma: no cover — только для отладки
        return (
            f"Cleaner(db={self._url.database!r}, schema={self._schema!r}, "
            f"strategy={self._strategy!r})"
        )
