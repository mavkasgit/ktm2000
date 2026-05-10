from collections.abc import AsyncIterator
import os
from urllib.parse import urlparse

import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool

from app.core.config import settings
from app.core.database import get_db
from app.main import app
from app.models.base import Base

@pytest_asyncio.fixture(scope="session", loop_scope="session")
async def test_database_url() -> AsyncIterator[str]:
    default_test_url = "postgresql+asyncpg://ktm2000_user:ktm2000_pass_test@localhost:5212/ktm2000_test"
    url = os.getenv("TEST_DATABASE_URL") or default_test_url

    # Hard safety: never allow tests to run against current app DB URL.
    if url.strip() == settings.DATABASE_URL.strip():
        raise RuntimeError(
            "Unsafe test DB configuration: TEST_DATABASE_URL points to active DATABASE_URL. "
            "Use a dedicated test database."
        )

    parsed = urlparse(url.replace("postgresql+asyncpg://", "postgresql://"))
    db_name = (parsed.path or "").lstrip("/")
    if "test" not in db_name.lower():
        raise RuntimeError(
            f"Unsafe test DB name '{db_name}'. TEST_DATABASE_URL must target a dedicated test database."
        )

    yield url


@pytest_asyncio.fixture(scope="session", loop_scope="session")
async def engine(test_database_url: str):
    engine = create_async_engine(test_database_url, poolclass=NullPool)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
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




