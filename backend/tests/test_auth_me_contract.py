"""Единый контракт /auth/me/* (канон user-settings 2.0.0) — KTM-копия HRMS."""

from __future__ import annotations

import pytest

pytestmark = pytest.mark.asyncio


async def test_me_profile_theme_locale_and_avatar_patch(auth_client) -> None:
    """theme/locale — предпочтения, принимаются; аватар — только через /me/avatar."""
    profile = await auth_client.patch(
        "/api/auth/me/profile",
        json={"theme": "dark", "locale": "en"},
    )
    assert profile.status_code == 200
    body = profile.json()
    assert body["theme"] == "dark"
    assert body["locale"] == "en"

    avatar = await auth_client.patch(
        "/api/auth/me/avatar",
        json={"avatar_seed": "deadbeef"},
    )
    assert avatar.status_code == 200
    assert avatar.json()["avatar_seed"] == "deadbeef"


async def test_me_profile_full_name_email_blocked_403(auth_client) -> None:
    """Канон 2.0.0: ФИО/email read-only — PATCH /auth/me/profile → 403."""
    for payload in (
        {"full_name": "New Name"},
        {"full_name": "Test Auth User"},  # совпадает с текущим — всё равно 403
        {"email": "new@example.com"},
        {"full_name": "New Name", "theme": "dark"},
        {"email": "new@example.com", "locale": "ru"},
    ):
        res = await auth_client.patch("/api/auth/me/profile", json=payload)
        assert res.status_code == 403, payload
        assert "администратор" in res.json()["detail"]


async def test_me_profile_avatar_fields_rejected_422(auth_client) -> None:
    """Канон 2.0.0: аватар меняется ТОЛЬКО через PATCH /auth/me/avatar.

    Поля avatar_seed/clear_avatar в /auth/me/profile больше не принимаются
    (единый контракт: profile = theme/locale) — Pydantic отдаёт 422.
    """
    for payload in ({"avatar_seed": "deadbeef"}, {"clear_avatar": True}):
        res = await auth_client.patch("/api/auth/me/profile", json=payload)
        assert res.status_code == 422, payload


async def test_me_avatar_null_resets_seed(auth_client) -> None:
    """PATCH /auth/me/avatar с NULL — сброс аватара (пустая заглушка на UI)."""
    await auth_client.patch("/api/auth/me/avatar", json={"avatar_seed": "deadbeef"})
    res = await auth_client.patch("/api/auth/me/avatar", json={"avatar_seed": None})
    assert res.status_code == 200
    assert res.json()["avatar_seed"] is None


async def test_me_login_events_capped_at_10_with_total(auth_client, session) -> None:
    """Канон 2.1.0: /auth/me/login-events отдаёт максимум 10 + total (окно 90 дней)."""
    from sqlalchemy import select

    from app.models.user import User
    from app.services.session_service import record_login_event

    res = await session.execute(select(User).where(User.username == "testauth"))
    user = res.scalar_one()
    for _ in range(12):
        await record_login_event(
            session,
            event_type="login_success",
            success=True,
            user_id=user.id,
            username_attempted=user.username,
        )
    await session.commit()

    res = await auth_client.get("/api/auth/me/login-events")
    assert res.status_code == 200
    body = res.json()
    assert body["total"] == 12
    assert len(body["events"]) == 10
    # Самые свежие сверху: id убывают (created_at DESC, tiebreaker id DESC).
    ids = [e["id"] for e in body["events"]]
    assert ids == sorted(ids, reverse=True)
