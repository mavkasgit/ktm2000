"""Drop all user tables/types in dev DB for migration baseline reset."""

from __future__ import annotations

import asyncio
import os

from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine


async def main() -> None:
    url = os.getenv(
        "DATABASE_URL",
        "postgresql+asyncpg://ktm2000_user:ktm2000_pass@localhost:5432/ktm2000_dev",
    )
    engine = create_async_engine(url, isolation_level="AUTOCOMMIT")
    async with engine.connect() as conn:
        await conn.execute(text("DROP SCHEMA public CASCADE"))
        await conn.execute(text("CREATE SCHEMA public"))
        await conn.execute(text("GRANT ALL ON SCHEMA public TO public"))
    await engine.dispose()
    print("Dev database reset: public schema recreated.")


if __name__ == "__main__":
    asyncio.run(main())