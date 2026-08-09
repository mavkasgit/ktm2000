from __future__ import annotations

from collections.abc import AsyncIterator
import os
import re
import tempfile
import uuid

os.environ.setdefault("DEV_BYPASS_AUTH", "true")

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy import text
from sqlalchemy.engine import URL, make_url
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool

from app.core.config import settings
from app.core.database import get_db
from app.main import app
from app.models.base import Base


# Тесты пишут только во временный каталог: не зависеть от env-переменных
# окружения (в т.ч. линуксовых /app/* путей) и дефолтов конфига.
_TEST_STORAGE_ROOT = os.path.join(tempfile.gettempdir(), "ktm2000_pytest_storage")
os.environ["IMPORT_STORAGE_DIR"] = os.path.join(_TEST_STORAGE_ROOT, "imports")
os.environ["PRODUCT_PHOTO_DIR"] = os.path.join(_TEST_STORAGE_ROOT, "products")
os.environ["BACKUPS_PATH"] = os.path.join(_TEST_STORAGE_ROOT, "backups")


DEFAULT_TEST_DATABASE_URL = "postgresql+asyncpg://ktm2000_user:ktm2000_pass_test@localhost:5441/ktm2000_test"
DB_MODE_HYBRID = "hybrid"
TEST_SCHEMA_PREFIX = "t_"
IDENT_RE = re.compile(r"^[a-zA-Z0-9_]+$")
RUN_DB_RE = re.compile(r"^ktm2000_test_[0-9a-f]{12}$")
_RUN_ID_ENV = "TEST_RUN_ID"

# The test launcher (scripts/test-run.ps1) owns the lifecycle of the run
# database: it creates ktm2000_test_<12 hex>, exports TEST_RUN_ID /
# TEST_DB_NAME / TEST_DATABASE_URL, runs pytest and drops the DB in a
# finally. This module never creates or drops databases — it only connects
# to the run-DB the launcher provided and isolates per-module schemas
# (t_<uuid8>) inside it.


def _quote_ident(name: str) -> str:
    return '"' + name.replace('"', '""') + '"'


def _validate_ident(name: str, *, required_prefix: str) -> None:
    if not name.startswith(required_prefix):
        raise RuntimeError(f"Unsafe identifier '{name}': expected prefix '{required_prefix}'.")
    if not IDENT_RE.fullmatch(name):
        raise RuntimeError(f"Unsafe identifier '{name}': only [a-zA-Z0-9_] is allowed.")


def _safe_schema_name() -> str:
    schema_name = f"{TEST_SCHEMA_PREFIX}{uuid.uuid4().hex[:8]}"
    _validate_ident(schema_name, required_prefix=TEST_SCHEMA_PREFIX)
    return schema_name


def _ensure_hybrid_mode() -> str:
    mode = (os.getenv("PYTEST_DB_MODE") or DB_MODE_HYBRID).strip().lower()
    if mode != DB_MODE_HYBRID:
        raise RuntimeError(
            f"Unsupported PYTEST_DB_MODE='{mode}'. Supported value: '{DB_MODE_HYBRID}'."
        )
    return mode


def _resolve_test_db_url(config) -> URL:
    """Resolve and validate the DB the suite runs against.

    Launcher mode (TEST_DATABASE_URL set) requires a launcher-owned run-DB
    name (ktm2000_test_<12 hex>). Manual debug mode (no env) allows raw
    serial pytest on the shared static DB, but refuses parallel (-n) runs
    that would race on it.
    """
    raw = os.getenv("TEST_DATABASE_URL")
    if raw:
        url = make_url(raw)
        db_name = (url.database or "").lower()
        if not RUN_DB_RE.fullmatch(db_name):
            raise RuntimeError(
                f"Unsafe TEST_DATABASE_URL database {url.database!r}: "
                f"expected launcher-owned run-DB matching {RUN_DB_RE.pattern}. "
                "Run through `npm run test:pytest`."
            )
    else:
        numprocesses = getattr(config.option, "numprocesses", 0)
        if numprocesses:
            raise RuntimeError(
                "Parallel pytest (-n) without TEST_DATABASE_URL is refused: it "
                "would race on the shared static DB. Run through "
                "`npm run test:pytest` to get an isolated per-run database."
            )
        url = make_url(DEFAULT_TEST_DATABASE_URL)
        db_name = (url.database or "").lower()
        if "test" not in db_name:
            raise RuntimeError(
                f"Unsafe TEST_DATABASE_URL database {url.database!r}. It must contain 'test'."
            )

    app_db = make_url(settings.DATABASE_URL)
    if settings.ENV != "test":
        same_target = (
            (url.host or "") == (app_db.host or "")
            and (url.port or 0) == (app_db.port or 0)
            and (url.database or "") == (app_db.database or "")
        )
        if same_target:
            raise RuntimeError(
                "Unsafe DB target: TEST_DATABASE_URL points to active app DATABASE_URL in non-test ENV."
            )
    return url


def pytest_sessionstart(session: pytest.Session) -> None:
    """Validate the DB contract before xdist spawns workers.

    Raising here aborts cleanly before any worker touches a database.
    """
    _resolve_test_db_url(session.config)


def pytest_report_header(config: pytest.Config) -> list[str]:
    run_id = os.getenv(_RUN_ID_ENV, "unknown")
    db_name = os.getenv("TEST_DB_NAME", "unknown")
    return [
        f"TEST_RUN_ID: {run_id}",
        f"TEST_DB_NAME: {db_name}",
    ]


# Mirrors alembic/versions/020_storage_vs_production.py trigger functions.
# Tests use ``Base.metadata.create_all`` to build the schema (no migration history),
# so we must attach the same trigger-based constraints that production has.
# PostgreSQL CHECK constraints cannot reference other tables, hence triggers.
#
# Implemented via raw asyncpg (no prepared statements) because the dollar-quoted
# PL/pgSQL bodies confuse asyncpg's "multiple statements in one prepared statement"
# detection.
_TRIGGERS_SQL = [
    """
    CREATE OR REPLACE FUNCTION fn_check_section_op_transport_on_storage()
    RETURNS TRIGGER AS $tg1$
    DECLARE
        sec_kind text;
    BEGIN
        IF NEW.operation_type = 'transport' THEN
            SELECT type INTO sec_kind FROM sections WHERE id = NEW.section_id;
            IF sec_kind IS NULL OR NOT (sec_kind IN ('raw_stock', 'wip_stock', 'finished_stock', 'scrap')) THEN
                RAISE EXCEPTION 'SectionOperation.operation_type=transport requires storage kind; got kind=% section_id=%', sec_kind, NEW.section_id
                    USING ERRCODE = 'check_violation';
            END IF;
        END IF;
        RETURN NEW;
    END;
    $tg1$ LANGUAGE plpgsql;
    """,
    "DROP TRIGGER IF EXISTS trg_section_op_transport_on_storage ON section_operations;",
    """
    CREATE TRIGGER trg_section_op_transport_on_storage
    BEFORE INSERT OR UPDATE OF operation_type, section_id ON section_operations
    FOR EACH ROW
    EXECUTE FUNCTION fn_check_section_op_transport_on_storage();
    """,
    """
    CREATE OR REPLACE FUNCTION fn_check_route_stage_transit_invariants()
    RETURNS TRIGGER AS $tg2$
    DECLARE
        sec_kind text;
    BEGIN
        IF NEW.stage_kind = 'transit' THEN
            IF NEW.section_id IS NOT NULL THEN
                RAISE EXCEPTION 'RouteStage.stage_kind=transit requires section_id IS NULL; got section_id=%', NEW.section_id
                    USING ERRCODE = 'check_violation';
            END IF;
            IF NEW.storage_section_id IS NULL THEN
                RAISE EXCEPTION 'RouteStage.stage_kind=transit requires storage_section_id IS NOT NULL'
                    USING ERRCODE = 'check_violation';
            END IF;
            SELECT type INTO sec_kind FROM sections WHERE id = NEW.storage_section_id;
            IF sec_kind IS NULL OR NOT (sec_kind IN ('raw_stock', 'wip_stock', 'finished_stock', 'scrap')) THEN
                RAISE EXCEPTION 'RouteStage.storage_section_id must reference a storage section; got kind=% storage_section_id=%', sec_kind, NEW.storage_section_id
                    USING ERRCODE = 'check_violation';
            END IF;
        END IF;
        RETURN NEW;
    END;
    $tg2$ LANGUAGE plpgsql;
    """,
    "DROP TRIGGER IF EXISTS trg_route_stage_transit_invariants ON route_stages;",
    """
    CREATE TRIGGER trg_route_stage_transit_invariants
    BEFORE INSERT OR UPDATE OF stage_kind, section_id, storage_section_id ON route_stages
    FOR EACH ROW
    EXECUTE FUNCTION fn_check_route_stage_transit_invariants();
    """,
]


async def _install_storage_vs_production_triggers(conn) -> None:
    import asyncpg

    raw = await conn.get_raw_connection()
    driver_conn = raw.driver_connection
    # asyncpg's raw connection doesn't honour the SET search_path issued by
    # SQLAlchemy — apply it explicitly so the triggers resolve tables in the
    # per-test schema.
    schema = (await conn.execute(text("SHOW search_path"))).scalar() or "public"
    # Strip quoting and pick the first schema if multiple are listed
    first_schema = schema.split(",")[0].strip().strip('"')
    await driver_conn.execute(f'SET search_path TO "{first_schema}"')
    for stmt in _TRIGGERS_SQL:
        await driver_conn.execute(stmt)


@pytest.fixture(scope="session")
def db_mode() -> str:
    return _ensure_hybrid_mode()


@pytest.fixture(scope="session")
def run_id(db_mode: str) -> str:
    _ = db_mode
    return os.environ.get(_RUN_ID_ENV) or uuid.uuid4().hex[:8]


@pytest.fixture(scope="session")
def base_test_db_url(db_mode: str, request: pytest.FixtureRequest) -> URL:
    _ = db_mode
    return _resolve_test_db_url(request.config)


@pytest.fixture(scope="module")
def module_schema_name() -> str:
    schema_name = f"{TEST_SCHEMA_PREFIX}{uuid.uuid4().hex[:8]}"
    _validate_ident(schema_name, required_prefix=TEST_SCHEMA_PREFIX)
    return schema_name


@pytest_asyncio.fixture(scope="module", loop_scope="module")
async def engine(
    base_test_db_url: URL,
    module_schema_name: str,
) -> AsyncIterator[AsyncEngine]:
    """Engine on the launcher-provided run-DB with a fresh schema per module.

    The run-DB is owned by the launcher and is deliberately NOT dropped here:
    dropping it in any single module's teardown would break the parallel
    xdist workers sharing it (the InvalidCatalogNameError this file used to
    guard against). The module schema (t_<uuid8>) is dropped instead; the
    run-DB itself is reaped by `npm run test:db:cleanup` if a run is killed.
    """
    eng = create_async_engine(
        base_test_db_url.render_as_string(hide_password=False), poolclass=NullPool
    )
    async with eng.begin() as conn:
        await conn.execute(text(f"CREATE SCHEMA IF NOT EXISTS {_quote_ident(module_schema_name)}"))
        await conn.execute(text(f"SET search_path TO {_quote_ident(module_schema_name)}"))
        await conn.run_sync(Base.metadata.create_all)
        await _install_storage_vs_production_triggers(conn)
    try:
        yield eng
    finally:
        # Drop the module schema to keep the shared run-DB clean
        try:
            async with eng.begin() as conn:
                await conn.execute(text(f"DROP SCHEMA IF EXISTS {_quote_ident(module_schema_name)} CASCADE"))
        except Exception:
            pass
        await eng.dispose()


@pytest_asyncio.fixture
async def session(engine: AsyncEngine, module_schema_name: str) -> AsyncIterator[AsyncSession]:
    async with engine.connect() as conn:
        transaction = await conn.begin()
        await conn.execute(text(f"SET search_path TO {_quote_ident(module_schema_name)}"))
        # Сброс генератора ID, чтобы system_user всегда получал id = 1
        await conn.execute(text("ALTER TABLE users ALTER COLUMN id RESTART WITH 1"))
        session_factory = async_sessionmaker(
            bind=conn,
            class_=AsyncSession,
            expire_on_commit=False,
            join_transaction_mode="create_savepoint"
        )
        async with session_factory() as db:
            from app.models.user import User, UserRole
            system_user = User(
                username="system",
                email="system@local",
                role=UserRole.admin,
                full_name="System User",
                is_active=True,
            )
            db.add(system_user)
            await db.commit()
            try:
                yield db
            finally:
                await db.rollback()
                await transaction.rollback()
        await conn.execute(text("SET search_path TO public"))


@pytest_asyncio.fixture
async def client(session: AsyncSession) -> AsyncIterator[AsyncClient]:
    async def override_get_db() -> AsyncIterator[AsyncSession]:
        try:
            yield session
        finally:
            await session.commit()

    app.dependency_overrides[get_db] = override_get_db

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac

    app.dependency_overrides.clear()


@pytest_asyncio.fixture
async def auth_client(session: AsyncSession) -> AsyncIterator[AsyncClient]:
    """Client with a valid JWT token in Authorization header."""
    from sqlalchemy import select
    from sqlalchemy.orm import selectinload

    from app.core.security import create_access_token
    from app.models.user import User, UserRole

    test_user = User(
        username="testauth",
        email="testauth@example.com",
        full_name="Test Auth User",
        role=UserRole.admin,
        is_active=True,
    )
    session.add(test_user)
    await session.commit()

    # Eager-load sections so MeResponse.section_ids does not trigger lazy IO
    loaded = await session.execute(
        select(User).where(User.id == test_user.id).options(selectinload(User.sections))
    )
    test_user = loaded.scalar_one()

    # Generate JWT token
    token = create_access_token(subject=test_user.username)

    # Override get_current_user to return test_user directly (no DB lookup)
    from app.api.deps import get_current_user
    app.dependency_overrides[get_current_user] = lambda: test_user

    async def override_get_db() -> AsyncIterator[AsyncSession]:
        try:
            yield session
        finally:
            await session.commit()

    app.dependency_overrides[get_db] = override_get_db

    transport = ASGITransport(app=app)
    try:
        async with AsyncClient(
            transport=transport,
            base_url="http://test",
            headers={"Authorization": f"Bearer {token}"},
        ) as ac:
            yield ac
    finally:
        app.dependency_overrides.clear()
