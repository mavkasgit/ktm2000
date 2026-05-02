import uuid
from collections.abc import AsyncIterator

import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy import text
from sqlalchemy.engine import make_url
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool

from app.core.database import get_db
from app.main import app
from app.models.base import Base

DEFAULT_TEST_DATABASE_URL = "postgresql+asyncpg://factoryflow_user:factoryflow_pass_test@localhost:5212/factoryflow_test"


def _quote_ident(value: str) -> str:
    return '"' + value.replace('"', '""') + '"'


@pytest_asyncio.fixture(scope="session", loop_scope="session")
async def test_database_url() -> AsyncIterator[str]:
    base_url = make_url(DEFAULT_TEST_DATABASE_URL)
    db_name = f"factoryflow_test_{uuid.uuid4().hex[:8]}"
    test_url = base_url.set(database=db_name)
    admin_url = base_url.set(database="postgres")

    admin_engine = create_async_engine(
        admin_url.render_as_string(hide_password=False),
        isolation_level="AUTOCOMMIT",
        poolclass=NullPool,
    )

    async with admin_engine.connect() as conn:
        await conn.execute(text(f"DROP DATABASE IF EXISTS {_quote_ident(db_name)} WITH (FORCE)"))
        await conn.execute(text(f"CREATE DATABASE {_quote_ident(db_name)}"))

    await admin_engine.dispose()

    try:
        yield test_url.render_as_string(hide_password=False)
    finally:
        admin_engine = create_async_engine(
            admin_url.render_as_string(hide_password=False),
            isolation_level="AUTOCOMMIT",
            poolclass=NullPool,
        )
        async with admin_engine.connect() as conn:
            await conn.execute(text(f"DROP DATABASE IF EXISTS {_quote_ident(db_name)} WITH (FORCE)"))
        await admin_engine.dispose()


@pytest_asyncio.fixture(scope="session", loop_scope="session")
async def engine(test_database_url: str):
    engine = create_async_engine(test_database_url, poolclass=NullPool)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    try:
        yield engine
    finally:
        await engine.dispose()


@pytest_asyncio.fixture
async def session(engine) -> AsyncIterator[AsyncSession]:
    session_factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    async with session_factory() as db:
        yield db
        await db.rollback()
        for table in reversed(Base.metadata.sorted_tables):
            await db.execute(table.delete())
        await db.commit()


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




