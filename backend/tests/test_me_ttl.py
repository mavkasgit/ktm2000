import pytest
from datetime import datetime, timezone, timedelta
from unittest.mock import AsyncMock, patch
from sqlalchemy import select
from app.core.config import settings
from app.models.user import User
from app.services.unified_profile_service import UnifiedProfile


@pytest.fixture
def idp_enabled(monkeypatch):
    monkeypatch.setattr(settings, "AUTH_OIDC_ENABLED", True)
    monkeypatch.setattr(settings, "AUTHENTIK_API_URL", "http://localhost:9000")
    monkeypatch.setattr(settings, "AUTHENTIK_API_TOKEN", "test-token")


@pytest.mark.asyncio
async def test_me_second_call_within_ttl_skips_pull(auth_client, session, idp_enabled):
    stmt = select(User).where(User.username == "testauth")
    res = await session.execute(stmt)
    user = res.scalar_one()
    user.authentik_sub = "sub-123"
    await session.commit()

    mock_profile = UnifiedProfile(
        full_name="Fresh Name",
        avatar_seed="freshseed",
        email="testauth@example.com",
        locale="ru",
        theme="dark",
        authentik_pk=9,
        source="idp",
    )

    with patch(
        "app.api.routes.auth.sync_local_from_idp",
        new_callable=AsyncMock,
        return_value=mock_profile,
    ) as mock_sync:
        # 1. Первый запрос (кеш пуст) -> должен дернуть sync_local_from_idp
        res1 = await auth_client.get("/api/auth/me")
        assert res1.status_code == 200
        assert mock_sync.call_count == 1
        assert res1.json()["full_name"] == "Fresh Name"

        # 2. Второй запрос подряд -> должен пропустить pull (skip)
        res2 = await auth_client.get("/api/auth/me")
        assert res2.status_code == 200
        assert mock_sync.call_count == 1


@pytest.mark.asyncio
async def test_me_refresh_forces_pull(auth_client, session, idp_enabled):
    stmt = select(User).where(User.username == "testauth")
    res = await session.execute(stmt)
    user = res.scalar_one()
    user.authentik_sub = "sub-456"
    await session.commit()

    mock_profile = UnifiedProfile(
        full_name="Fresh Name 2",
        avatar_seed="freshseed2",
        email="testauth@example.com",
        locale="ru",
        theme="dark",
        authentik_pk=10,
        source="idp",
    )

    with patch(
        "app.api.routes.auth.sync_local_from_idp",
        new_callable=AsyncMock,
        return_value=mock_profile,
    ) as mock_sync:
        # 1. Первый запрос
        res1 = await auth_client.get("/api/auth/me")
        assert res1.status_code == 200
        assert mock_sync.call_count == 1

        # 2. Второй запрос с refresh=1 -> форсирует pull
        res2 = await auth_client.get("/api/auth/me?refresh=1")
        assert res2.status_code == 200
        assert mock_sync.call_count == 2


@pytest.mark.asyncio
async def test_me_ttl_zero_always_pulls(auth_client, session, idp_enabled, monkeypatch):
    monkeypatch.setattr(settings, "AUTHENTIK_PROFILE_TTL_SECONDS", 0)

    stmt = select(User).where(User.username == "testauth")
    res = await session.execute(stmt)
    user = res.scalar_one()
    user.authentik_sub = "sub-789"
    await session.commit()

    mock_profile = UnifiedProfile(
        full_name="Fresh Name 3",
        avatar_seed="freshseed3",
        email="testauth@example.com",
        locale="ru",
        theme="dark",
        authentik_pk=11,
        source="idp",
    )

    with patch(
        "app.api.routes.auth.sync_local_from_idp",
        new_callable=AsyncMock,
        return_value=mock_profile,
    ) as mock_sync:
        # 1. Первый запрос
        res1 = await auth_client.get("/api/auth/me")
        assert res1.status_code == 200
        assert mock_sync.call_count == 1

        # 2. Второй запрос -> при TTL=0 тоже вызывает pull
        res2 = await auth_client.get("/api/auth/me")
        assert res2.status_code == 200
        assert mock_sync.call_count == 2


@pytest.mark.asyncio
async def test_me_stale_cache_pulls(auth_client, session, idp_enabled):
    stmt = select(User).where(User.username == "testauth")
    res = await session.execute(stmt)
    user = res.scalar_one()
    user.authentik_sub = "sub-101112"
    user.profile_synced_at = datetime.now(timezone.utc) - timedelta(minutes=10)
    await session.commit()

    mock_profile = UnifiedProfile(
        full_name="Fresh Name 4",
        avatar_seed="freshseed4",
        email="testauth@example.com",
        locale="ru",
        theme="dark",
        authentik_pk=12,
        source="idp",
    )

    with patch(
        "app.api.routes.auth.sync_local_from_idp",
        new_callable=AsyncMock,
        return_value=mock_profile,
    ) as mock_sync:
        res = await auth_client.get("/api/auth/me")
        assert res.status_code == 200
        assert mock_sync.call_count == 1
