import pytest
from sqlalchemy import text


@pytest.mark.asyncio
async def test_hybrid_session_uses_temp_schema(session) -> None:
    current_schema = await session.scalar(text("SELECT current_schema()"))
    assert current_schema is not None
    assert current_schema.startswith("t_")


@pytest.mark.asyncio
async def test_hybrid_isolation_can_write_data(session) -> None:
    await session.execute(
        text(
            "INSERT INTO sections (code, name, kind, is_active) "
            "VALUES ('HYB-1', 'Hybrid Section', 'production', true)"
        )
    )
    await session.commit()

    count = await session.scalar(text("SELECT COUNT(*) FROM sections WHERE code = 'HYB-1'"))
    assert count == 1


@pytest.mark.asyncio
async def test_hybrid_isolation_starts_clean_for_next_test(session) -> None:
    count = await session.scalar(text("SELECT COUNT(*) FROM sections WHERE code = 'HYB-1'"))
    assert count == 0
