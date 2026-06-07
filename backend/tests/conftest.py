from __future__ import annotations

from collections.abc import AsyncIterator
import os
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


DEFAULT_TEST_DATABASE_URL = "postgresql+asyncpg://ktm2000_user:ktm2000_pass_test@localhost:5212/ktm2000_test"
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
    _validate_ident(db_name, required_prefix=TEST_DB_PREFIX)
    engine = await _open_autocommit_engine(admin_url)
    try:
        async with engine.connect() as conn:
            await conn.execute(text(f"CREATE DATABASE {_quote_ident(db_name)}"))
    finally:
        await engine.dispose()


async def _cleanup_stale_databases(admin_url: URL) -> None:
    engine = await _open_autocommit_engine(admin_url)
    try:
        async with engine.connect() as conn:
            rows = (
                await conn.execute(
                    text(
                        "SELECT datname "
                        "FROM pg_database "
                        "WHERE datname LIKE :prefix "
                        "ORDER BY datname"
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


@pytest_asyncio.fixture(scope="module", loop_scope="module")
async def module_db_url(
    request: pytest.FixtureRequest,
    run_id: str,
    base_test_db_url: URL,
    admin_db_url: URL,
) -> AsyncIterator[str]:
    module_name = request.module.__name__ if request.module else "module"
    db_name = _safe_module_db_name(module_name, run_id)
    await _create_database(admin_db_url, db_name)

    db_url = base_test_db_url.set(database=db_name).render_as_string(hide_password=False)
    try:
        yield db_url
    finally:
        await _drop_database(admin_db_url, db_name)


@pytest_asyncio.fixture
async def engine(module_db_url: str) -> AsyncIterator[AsyncEngine]:
    engine = create_async_engine(module_db_url, poolclass=NullPool)
    try:
        yield engine
    finally:
        await engine.dispose()


@pytest_asyncio.fixture
async def session(engine: AsyncEngine) -> AsyncIterator[AsyncSession]:
    schema_name = _safe_schema_name()

    _validate_ident(schema_name, required_prefix=TEST_SCHEMA_PREFIX)

    async with engine.begin() as conn:
        await conn.execute(text(f"CREATE SCHEMA {_quote_ident(schema_name)}"))
        await conn.execute(text(f"SET search_path TO {_quote_ident(schema_name)}"))
        await conn.run_sync(Base.metadata.create_all)

    async with engine.connect() as conn:
        await conn.execute(text(f"SET search_path TO {_quote_ident(schema_name)}"))
        session_factory = async_sessionmaker(bind=conn, class_=AsyncSession, expire_on_commit=False)
        async with session_factory() as db:
            # Seed default system user (id=1) to prevent foreign key errors in audit logs
            from app.models.user import User, UserRole
            system_user = User(
                email="system@local",
                password_hash="",
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
        await conn.execute(text("SET search_path TO public"))

    async with engine.begin() as conn:
        await conn.execute(text(f"DROP SCHEMA {_quote_ident(schema_name)} CASCADE"))


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
