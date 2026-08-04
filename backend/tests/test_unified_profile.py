"""Unified profile service — Authentik attribute mapping (no live IdP)."""

from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest

from app.core.config import settings
from app.services import unified_profile_service as ups
from app.services.unified_profile_service import UnifiedProfile


@pytest.fixture
def idp_on():
    original = {
        "AUTH_OIDC_ENABLED": settings.AUTH_OIDC_ENABLED,
        "AUTHENTIK_API_URL": settings.AUTHENTIK_API_URL,
        "AUTHENTIK_API_TOKEN": settings.AUTHENTIK_API_TOKEN,
    }
    settings.AUTH_OIDC_ENABLED = True
    settings.AUTHENTIK_API_URL = "http://localhost:9000"
    settings.AUTHENTIK_API_TOKEN = "test-token"
    yield
    for k, v in original.items():
        setattr(settings, k, v)


@pytest.mark.asyncio
async def test_push_profile_maps_attributes(idp_on):
    ak = {
        "pk": 5,
        "uuid": "sub-1",
        "name": "Old",
        "email": "old@example.com",
        "attributes": {"other": "keep"},
    }
    calls: list = []

    async def fake_request(method, path, *, params=None, json_body=None):
        calls.append((method, path, json_body))
        if method == "GET" and path == "/core/users/":
            return {"results": [ak]}
        if method == "PATCH":
            out = dict(ak)
            out.update(json_body or {})
            if json_body and "attributes" in json_body:
                out["attributes"] = json_body["attributes"]
            if json_body and "name" in json_body:
                out["name"] = json_body["name"]
            if json_body and "email" in json_body:
                out["email"] = json_body["email"]
            return out
        return ak

    with patch.object(ups, "_request", side_effect=fake_request):
        result = await ups.push_profile_by_sub(
            "sub-1",
            full_name="New Name",
            avatar_seed="abcd1234",
            email="new@example.com",
            locale="en",
            theme="dark",
        )

    assert result.full_name == "New Name"
    assert result.avatar_seed == "abcd1234"
    assert result.email == "new@example.com"
    assert result.locale == "en"
    assert result.theme == "dark"
    patch_body = next(c[2] for c in calls if c[0] == "PATCH")
    assert patch_body["name"] == "New Name"
    assert patch_body["email"] == "new@example.com"
    assert patch_body["attributes"]["profile_avatar_seed"] == "abcd1234"
    assert patch_body["attributes"]["profile_locale"] == "en"
    assert patch_body["attributes"]["profile_theme"] == "dark"
    assert patch_body["attributes"]["other"] == "keep"


@pytest.mark.asyncio
async def test_profile_from_ak_user_reads_attrs():
    profile = ups.profile_from_ak_user(
        {
            "pk": 1,
            "name": "N",
            "email": "a@b.c",
            "attributes": {
                "profile_avatar_seed": "seed1",
                "profile_locale": "ru",
                "profile_theme": "system",
            },
        }
    )
    assert profile.email == "a@b.c"
    assert profile.locale == "ru"
    assert profile.theme == "system"
    assert profile.avatar_seed == "seed1"


@pytest.mark.asyncio
async def test_sync_local_from_idp_no_name_email_push(idp_on):
    """Канон 2.0.0: bootstrap-push ФИО/email удалён — при пустом удалённом
    full_name/email НЕ пишутся в Authentik (только avatar_seed)."""
    import uuid as uuid_mod

    sub = f"sub-{uuid_mod.uuid4().hex}"
    remote = UnifiedProfile(
        full_name=None,
        avatar_seed=None,
        email=None,
        authentik_pk=1,
        source="idp",
    )
    bootstrapped = UnifiedProfile(
        full_name=None,
        avatar_seed="aabbccdd",
        email=None,
        authentik_pk=1,
        source="bootstrap",
    )

    with (
        patch(
            "app.services.unified_profile_service.fetch_profile_by_sub",
            new_callable=AsyncMock,
            return_value=remote,
        ),
        patch(
            "app.services.unified_profile_service.push_profile_by_sub",
            new_callable=AsyncMock,
            return_value=bootstrapped,
        ) as push,
    ):
        snapshot = await ups.sync_local_from_idp(
            authentik_sub=sub,
            local_full_name="Local Name",
            local_avatar_seed="aabbccdd",
            local_email="local@example.com",
        )

    assert snapshot is not None
    assert snapshot.avatar_seed == "aabbccdd"
    assert snapshot.source == "bootstrap"
    push.assert_awaited_once()
    assert push.await_args is not None
    assert push.await_args.args[0] == sub
    assert push.await_args.kwargs.get("avatar_seed") == "aabbccdd"
    assert "full_name" not in push.await_args.kwargs
    assert "email" not in push.await_args.kwargs


@pytest.mark.asyncio
async def test_profile_sync_disabled_without_token():
    original = settings.AUTHENTIK_API_TOKEN
    settings.AUTHENTIK_API_TOKEN = ""
    try:
        assert ups.profile_sync_enabled() is False
    finally:
        settings.AUTHENTIK_API_TOKEN = original
