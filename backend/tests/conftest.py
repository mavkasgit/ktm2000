from __future__ import annotations

from collections.abc import AsyncIterator
import os
os.environ.setdefault("DEV_BYPASS_AUTH", "true")
os.environ.pop("TEST_DATABASE_URL", None)
import re
import uuid

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


DEFAULT_TEST_DATABASE_URL = "postgresql+asyncpg://ktm2000_user:ktm2000_pass_test@localhost:5441/ktm2000_test"
DB_MODE_HYBRID = "hybrid"
TEST_DB_PREFIX = "ktm_test_"
TEST_SCHEMA_PREFIX = "t_"
IDENT_RE = re.compile(r"^[a-zA-Z0-9_]+$")


def _quote_ident(name: str) -> str:
    return '"' + name.replace('"', '""') + '"'


def _normalize_token(value: str, *, fallback: str) -> str:
    token = re.sub(r"[^a-zA-Z0-9_]+", "_", value).strip("_").lower()
    return token or fallback


def _validate_ident(name: str, *, required_prefix: str) -> None:
    if not name.startswith(required_prefix):
        raise RuntimeError(f"Unsafe identifier '{name}': expected prefix '{required_prefix}'.")
    if not IDENT_RE.fullmatch(name):
        raise RuntimeError(f"Unsafe identifier '{name}': only [a-zA-Z0-9_] is allowed.")


def _safe_module_db_name(module_name: str, run_id: str) -> str:
    token = _normalize_token(module_name, fallback="module")
    reserved = len(TEST_DB_PREFIX) + len(run_id) + 1
    token = token[: max(1, 63 - reserved)]
    db_name = f"{TEST_DB_PREFIX}{token}_{run_id}"
    _validate_ident(db_name, required_prefix=TEST_DB_PREFIX)
    return db_name


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


def _base_test_db_url() -> URL:
    raw = os.getenv("TEST_DATABASE_URL") or DEFAULT_TEST_DATABASE_URL
    base = make_url(raw)

    db_name = (base.database or "").lower()
    if "test" not in db_name:
        raise RuntimeError(
            f"Unsafe TEST_DATABASE_URL database '{base.database}'. It must contain 'test'."
        )

    app_db = make_url(settings.DATABASE_URL)
    if settings.ENV != "test":
        same_target = (
            (base.host or "") == (app_db.host or "")
            and (base.port or 0) == (app_db.port or 0)
            and (base.database or "") == (app_db.database or "")
        )
        if same_target:
            raise RuntimeError(
                "Unsafe DB target: TEST_DATABASE_URL points to active app DATABASE_URL in non-test ENV."
            )

    return base


def _admin_db_url(base_url: URL) -> URL:
    admin_db = (os.getenv("PYTEST_DB_ADMIN_DB") or "postgres").strip() or "postgres"
    admin_url = base_url.set(database=admin_db)
    return admin_url


async def _open_autocommit_engine(url: URL) -> AsyncEngine:
    return create_async_engine(
        url.render_as_string(hide_password=False),
        poolclass=NullPool,
        isolation_level="AUTOCOMMIT",
    )


async def _drop_database(admin_url: URL, db_name: str) -> None:
    _validate_ident(db_name, required_prefix=TEST_DB_PREFIX)
    engine = await _open_autocommit_engine(admin_url)
    try:
        async with engine.connect() as conn:
            await conn.execute(
                text(
                    "SELECT pg_terminate_backend(pid) "
                    "FROM pg_stat_activity "
                    "WHERE datname = :db_name AND pid <> pg_backend_pid()"
                ),
                {"db_name": db_name},
            )
            await conn.execute(text(f"DROP DATABASE IF EXISTS {_quote_ident(db_name)}"))
    finally:
        await engine.dispose()


async def _create_database(admin_url: URL, db_name: str) -> None:
    """Create a test database, tolerating 'already exists' from parallel workers."""
    _validate_ident(db_name, required_prefix=TEST_DB_PREFIX)
    engine = await _open_autocommit_engine(admin_url)
    try:
        async with engine.connect() as conn:
            try:
                await conn.execute(text(f"CREATE DATABASE {_quote_ident(db_name)}"))
            except Exception as exc:
                # asyncpg raises DuplicateDatabaseError (42P04) if another
                # worker created it first — safe to ignore.
                raw = getattr(exc, "sqlstate", None) or ""
                if raw == "42P04" or "already exists" in str(exc).lower():
                    pass
                else:
                    raise
    finally:
        await engine.dispose()


async def _cleanup_stale_databases(admin_url: URL) -> None:
    """Drop leftover test databases from previous runs.

    Skips databases with active connections to avoid racing with
    freshly created DBs from parallel xdist workers.
    """
    engine = await _open_autocommit_engine(admin_url)
    try:
        async with engine.connect() as conn:
            rows = (
                await conn.execute(
                    text(
                        "SELECT d.datname "
                        "FROM pg_database d "
                        "WHERE d.datname LIKE :prefix "
                        "AND NOT EXISTS ("
                        "  SELECT 1 FROM pg_stat_activity a "
                        "  WHERE a.datname = d.datname AND a.pid <> pg_backend_pid()"
                        ") "
                        "ORDER BY d.datname"
                    ),
                    {"prefix": f"{TEST_DB_PREFIX}%"},
                )
            ).fetchall()

        for row in rows:
            db_name = row[0]
            try:
                _validate_ident(db_name, required_prefix=TEST_DB_PREFIX)
            except RuntimeError:
                continue
            await _drop_database(admin_url, db_name)
    finally:
        await engine.dispose()


async def _ensure_createdb_privilege(admin_url: URL) -> None:
    engine = await _open_autocommit_engine(admin_url)
    try:
        async with engine.connect() as conn:
            can_createdb = await conn.scalar(
                text(
                    "SELECT r.rolcreatedb "
                    "FROM pg_roles r "
                    "WHERE r.rolname = current_user"
                )
            )
        if not bool(can_createdb):
            raise RuntimeError(
                "Hybrid DB mode requires CREATEDB privilege for current DB user. "
                "Grant CREATEDB or switch test credentials."
            )
    finally:
        await engine.dispose()


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
    return uuid.uuid4().hex[:8]


@pytest.fixture(scope="session")
def base_test_db_url(db_mode: str) -> URL:
    _ = db_mode
    return _base_test_db_url()


@pytest.fixture(scope="session")
def admin_db_url(base_test_db_url: URL) -> URL:
    return _admin_db_url(base_test_db_url)


@pytest_asyncio.fixture(scope="session", autouse=True, loop_scope="session")
async def cleanup_stale_test_dbs(db_mode: str, admin_db_url: URL) -> AsyncIterator[None]:
    _ = db_mode
    await _ensure_createdb_privilege(admin_db_url)
    await _cleanup_stale_databases(admin_db_url)
    yield


@pytest_asyncio.fixture(scope="session", loop_scope="session")
async def worker_db_url(
    run_id: str,
    base_test_db_url: URL,
    admin_db_url: URL,
) -> AsyncIterator[str]:
    """One database per xdist worker (session-scoped). Modules share it via schemas."""
    db_name = f"{TEST_DB_PREFIX}w_{run_id}"
    _validate_ident(db_name, required_prefix=TEST_DB_PREFIX)
    await _create_database(admin_db_url, db_name)
    db_url = base_test_db_url.set(database=db_name).render_as_string(hide_password=False)
    try:
        yield db_url
    finally:
        await _drop_database(admin_db_url, db_name)


@pytest_asyncio.fixture(scope="module", loop_scope="module")
async def module_schema_name() -> str:
    schema_name = f"{TEST_SCHEMA_PREFIX}{uuid.uuid4().hex[:8]}"
    _validate_ident(schema_name, required_prefix=TEST_SCHEMA_PREFIX)
    return schema_name


@pytest_asyncio.fixture(scope="module", loop_scope="module")
async def engine(
    worker_db_url: str,
    module_schema_name: str,
) -> AsyncIterator[AsyncEngine]:
    """Create engine on the shared worker DB with a fresh schema per module."""
    eng = create_async_engine(worker_db_url, poolclass=NullPool)
    async with eng.begin() as conn:
        await conn.execute(text(f"CREATE SCHEMA IF NOT EXISTS {_quote_ident(module_schema_name)}"))
        await conn.execute(text(f"SET search_path TO {_quote_ident(module_schema_name)}"))
        await conn.run_sync(Base.metadata.create_all)
        await _install_storage_vs_production_triggers(conn)
    try:
        yield eng
    finally:
        # Drop the module schema to keep the shared DB clean
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
