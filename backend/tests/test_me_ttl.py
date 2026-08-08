import pytest
from datetime import datetime, timezone, timedelta
from unittest.mock import AsyncMock, patch
from sqlalchemy import select
from app.core.config import settings
from app.models.user import User
from app.services.authentik_client import AuthentikAdminError
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
        "app.services.unified_profile_service.sync_local_from_idp",
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
        "app.services.unified_profile_service.sync_local_from_idp",
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
        "app.services.unified_profile_service.sync_local_from_idp",
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
        "app.services.unified_profile_service.sync_local_from_idp",
        new_callable=AsyncMock,
        return_value=mock_profile,
    ) as mock_sync:
        res = await auth_client.get("/api/auth/me")
        assert res.status_code == 200
        assert mock_sync.call_count == 1


@pytest.mark.asyncio
async def test_me_pull_failure_keeps_cache_and_marks_failed_at(
    auth_client, session, idp_enabled
):
    """IdP failure → 200 with cache; profile_synced_at untouched, failed_at set."""
    stmt = select(User).where(User.username == "testauth")
    res = await session.execute(stmt)
    user = res.scalar_one()
    user.authentik_sub = "sub-fail-1"
    user.full_name = "Cached Name"
    user.profile_synced_at = datetime.now(timezone.utc) - timedelta(minutes=30)
    synced_before = user.profile_synced_at
    await session.commit()

    with patch(
        "app.services.unified_profile_service.sync_local_from_idp",
        new_callable=AsyncMock,
        side_effect=AuthentikAdminError("IdP down", status_code=502),
    ) as mock_sync:
        res1 = await auth_client.get("/api/auth/me")
        assert res1.status_code == 200
        assert res1.json()["full_name"] == "Cached Name"
        assert mock_sync.call_count == 1

    session.expire_all()
    updated = (
        await session.execute(select(User).where(User.username == "testauth"))
    ).scalar_one()
    assert updated.full_name == "Cached Name"
    assert updated.profile_synced_at == synced_before
    assert updated.profile_sync_failed_at is not None


@pytest.mark.asyncio
async def test_me_failure_cooldown_skips_second_pull(auth_client, session, idp_enabled):
    """After a failed pull the TTL cooldown prevents hammering the IdP."""
    stmt = select(User).where(User.username == "testauth")
    res = await session.execute(stmt)
    user = res.scalar_one()
    user.authentik_sub = "sub-fail-2"
    user.profile_synced_at = datetime.now(timezone.utc) - timedelta(minutes=30)
    await session.commit()

    with patch(
        "app.services.unified_profile_service.sync_local_from_idp",
        new_callable=AsyncMock,
        side_effect=AuthentikAdminError("IdP down", status_code=503),
    ) as mock_sync:
        res1 = await auth_client.get("/api/auth/me")
        assert res1.status_code == 200
        assert mock_sync.call_count == 1

        res2 = await auth_client.get("/api/auth/me")
        assert res2.status_code == 200
        assert mock_sync.call_count == 1


@pytest.mark.asyncio
async def test_me_not_found_sets_synced_at_and_skips_second_pull(
    auth_client, session, idp_enabled
):
    """not_found is an authoritative answer: synced_at=now, no failed_at, TTL skip."""
    stmt = select(User).where(User.username == "testauth")
    res = await session.execute(stmt)
    user = res.scalar_one()
    user.authentik_sub = "sub-notfound-1"
    user.profile_synced_at = datetime.now(timezone.utc) - timedelta(minutes=30)
    await session.commit()

    with patch(
        "app.services.unified_profile_service.sync_local_from_idp",
        new_callable=AsyncMock,
        return_value=None,
    ) as mock_sync:
        res1 = await auth_client.get("/api/auth/me")
        assert res1.status_code == 200
        assert mock_sync.call_count == 1

        session.expire_all()
        updated = (
            await session.execute(select(User).where(User.username == "testauth"))
        ).scalar_one()
        assert updated.profile_sync_failed_at is None
        assert updated.profile_synced_at is not None

        res2 = await auth_client.get("/api/auth/me")
        assert res2.status_code == 200
        assert mock_sync.call_count == 1


@pytest.mark.asyncio
async def test_me_refresh_recovers_after_failure(auth_client, session, idp_enabled):
    """refresh=1 forces a pull; success clears failed_at and refreshes the cache."""
    stmt = select(User).where(User.username == "testauth")
    res = await session.execute(stmt)
    user = res.scalar_one()
    user.authentik_sub = "sub-recover-1"
    user.profile_synced_at = datetime.now(timezone.utc) - timedelta(minutes=30)
    await session.commit()

    mock_profile = UnifiedProfile(
        full_name="Recovered Name",
        avatar_seed="recovseed",
        email="testauth@example.com",
        locale="ru",
        theme="dark",
        authentik_pk=13,
        source="idp",
    )

    with patch(
        "app.services.unified_profile_service.sync_local_from_idp",
        new_callable=AsyncMock,
        side_effect=[AuthentikAdminError("down", status_code=502), mock_profile],
    ) as mock_sync:
        res1 = await auth_client.get("/api/auth/me")
        assert res1.status_code == 200
        assert mock_sync.call_count == 1

        res2 = await auth_client.get("/api/auth/me?refresh=1")
        assert res2.status_code == 200
        assert res2.json()["full_name"] == "Recovered Name"
        assert mock_sync.call_count == 2

    session.expire_all()
    updated = (
        await session.execute(select(User).where(User.username == "testauth"))
    ).scalar_one()
    assert updated.full_name == "Recovered Name"
    assert updated.profile_sync_failed_at is None
    assert updated.profile_synced_at is not None
