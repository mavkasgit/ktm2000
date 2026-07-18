"""OIDC / Authentik bridge tests — mocked token endpoint + JWKS (no live IdP)."""

from __future__ import annotations

import json
import time
from unittest.mock import MagicMock, patch

import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from jose import jwt as jose_jwt
from jose.utils import base64url_encode
from sqlalchemy import select

from app.core.config import settings
from app.core.security import get_password_hash
from app.models.user import User, UserRole
from app.services.oidc_auth_service import OidcAuthService

ISSUER = "http://localhost:9000/application/o/ktm2000/"
CLIENT_ID = "ktm2000"
REDIRECT_URI = "http://localhost:8082/auth/callback"
KID = "test-key-1"


def _generate_rsa_pair():
    private_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    public_key = private_key.public_key()
    private_pem = private_key.private_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PrivateFormat.PKCS8,
        encryption_algorithm=serialization.NoEncryption(),
    )
    numbers = public_key.public_numbers()

    def _b64int(val: int) -> str:
        raw = val.to_bytes((val.bit_length() + 7) // 8 or 1, "big")
        return base64url_encode(raw).decode("ascii")

    jwk = {
        "kty": "RSA",
        "kid": KID,
        "use": "sig",
        "alg": "RS256",
        "n": _b64int(numbers.n),
        "e": _b64int(numbers.e),
    }
    return private_pem, {"keys": [jwk]}


_PRIVATE_PEM, _JWKS = _generate_rsa_pair()


def _make_id_token(
    *,
    sub: str = "ak-sub-uuid-001",
    preferred_username: str = "oidc_user",
    email: str | None = "oidc_user@example.com",
    name: str = "OIDC Test User",
    aud: str = CLIENT_ID,
    iss: str = ISSUER.rstrip("/"),
    exp_delta: int = 3600,
    groups: list[str] | None = None,
) -> str:
    now = int(time.time())
    claims: dict = {
        "sub": sub,
        "preferred_username": preferred_username,
        "name": name,
        "aud": aud,
        "iss": iss,
        "iat": now,
        "exp": now + exp_delta,
    }
    if email is not None:
        claims["email"] = email
    if groups is not None:
        claims["groups"] = groups
    return jose_jwt.encode(
        claims,
        _PRIVATE_PEM,
        algorithm="RS256",
        headers={"kid": KID},
    )


class _FakeResponse:
    def __init__(self, status_code: int, payload: dict | str):
        self.status_code = status_code
        self._payload = payload
        self.text = payload if isinstance(payload, str) else json.dumps(payload)

    def json(self):
        if isinstance(self._payload, str):
            return json.loads(self._payload)
        return self._payload

    def raise_for_status(self):
        if self.status_code >= 400:
            import httpx

            raise httpx.HTTPStatusError(
                "error",
                request=MagicMock(),
                response=MagicMock(status_code=self.status_code),
            )


class _FakeAsyncClient:
    def __init__(self, *, token_body: dict | None = None, token_status: int = 200, jwks=None):
        self.token_body = token_body
        self.token_status = token_status
        self.jwks = jwks if jwks is not None else _JWKS

    async def __aenter__(self):
        return self

    async def __aexit__(self, *args):
        return None

    async def post(self, url, data=None, headers=None, **kwargs):
        if self.token_body is None:
            return _FakeResponse(self.token_status, {"error": "invalid_grant"})
        return _FakeResponse(self.token_status, self.token_body)

    async def get(self, url, headers=None, **kwargs):
        return _FakeResponse(200, self.jwks)


@pytest.fixture
def oidc_enabled():
    originals = {
        "AUTH_OIDC_ENABLED": settings.AUTH_OIDC_ENABLED,
        "AUTH_OIDC_ISSUER": settings.AUTH_OIDC_ISSUER,
        "AUTH_OIDC_CLIENT_ID": settings.AUTH_OIDC_CLIENT_ID,
        "AUTH_OIDC_CLIENT_SECRET": settings.AUTH_OIDC_CLIENT_SECRET,
        "AUTH_OIDC_REDIRECT_URI": settings.AUTH_OIDC_REDIRECT_URI,
        "AUTH_OIDC_SCOPES": settings.AUTH_OIDC_SCOPES,
        "AUTH_OIDC_JWKS_URL": settings.AUTH_OIDC_JWKS_URL,
        "AUTH_OIDC_TOKEN_URL": settings.AUTH_OIDC_TOKEN_URL,
        "AUTH_OIDC_ALLOW_JIT": settings.AUTH_OIDC_ALLOW_JIT,
        "AUTH_OIDC_DEFAULT_ROLE": settings.AUTH_OIDC_DEFAULT_ROLE,
        "AUTH_OIDC_SYNC_ROLE_FROM_IDP": settings.AUTH_OIDC_SYNC_ROLE_FROM_IDP,
        "AUTH_OIDC_ISSUER_ALIASES": settings.AUTH_OIDC_ISSUER_ALIASES,
    }
    settings.AUTH_OIDC_ENABLED = True
    settings.AUTH_OIDC_ISSUER = ISSUER
    settings.AUTH_OIDC_CLIENT_ID = CLIENT_ID
    settings.AUTH_OIDC_CLIENT_SECRET = None
    settings.AUTH_OIDC_REDIRECT_URI = REDIRECT_URI
    settings.AUTH_OIDC_SCOPES = "openid profile email"
    settings.AUTH_OIDC_JWKS_URL = f"{ISSUER}jwks/"
    settings.AUTH_OIDC_TOKEN_URL = "http://localhost:9000/application/o/token/"
    settings.AUTH_OIDC_ALLOW_JIT = False
    settings.AUTH_OIDC_DEFAULT_ROLE = "viewer"
    settings.AUTH_OIDC_SYNC_ROLE_FROM_IDP = False
    settings.AUTH_OIDC_ISSUER_ALIASES = None
    OidcAuthService.clear_jwks_cache()
    try:
        yield
    finally:
        for k, v in originals.items():
            setattr(settings, k, v)
        OidcAuthService.clear_jwks_cache()


@pytest.fixture
def oidc_disabled():
    original = settings.AUTH_OIDC_ENABLED
    settings.AUTH_OIDC_ENABLED = False
    try:
        yield
    finally:
        settings.AUTH_OIDC_ENABLED = original


@pytest.mark.asyncio
async def test_oidc_config_disabled(client, oidc_disabled) -> None:
    response = await client.get("/api/auth/oidc/config")
    assert response.status_code == 200
    body = response.json()
    assert body["enabled"] is False
    assert body["client_id"] is None
    assert body["authorization_url"] is None


@pytest.mark.asyncio
async def test_oidc_config_enabled(client, oidc_enabled) -> None:
    response = await client.get("/api/auth/oidc/config")
    assert response.status_code == 200
    body = response.json()
    assert body["enabled"] is True
    assert body["client_id"] == CLIENT_ID
    assert body["redirect_uri"] == REDIRECT_URI
    assert body["issuer"] == ISSUER.rstrip("/")
    assert "openid" in (body["scopes"] or "")
    assert body["authorization_url"]
    assert "authorize" in body["authorization_url"]


@pytest.mark.asyncio
async def test_oidc_logout_url_enabled(client, oidc_enabled) -> None:
    response = await client.get("/api/auth/oidc/logout-url")
    assert response.status_code == 200
    body = response.json()
    assert body["enabled"] is True
    assert body["logout_url"]
    assert "end-session" in body["logout_url"]


@pytest.mark.asyncio
async def test_oidc_logout_url_disabled(client, oidc_disabled) -> None:
    response = await client.get("/api/auth/oidc/logout-url")
    assert response.status_code == 200
    body = response.json()
    assert body["enabled"] is False
    assert body.get("logout_url") in (None, "")


@pytest.mark.asyncio
async def test_oidc_callback_disabled_404(client, oidc_disabled) -> None:
    response = await client.post(
        "/api/auth/oidc/callback",
        json={
            "code": "x",
            "code_verifier": "y",
            "redirect_uri": REDIRECT_URI,
        },
    )
    assert response.status_code == 404


@pytest.mark.asyncio
async def test_oidc_callback_links_by_username_and_persists_sub(
    client, session, oidc_enabled
) -> None:
    """Secondary link by username writes authentik_sub; role preserved (SYNC off)."""
    user = User(
        username="oidc_user",
        email="oidc_user@example.com",
        password_hash=get_password_hash("password123"),
        full_name="OIDC Local User",
        role=UserRole.planner,
        is_active=True,
    )
    session.add(user)
    await session.commit()
    user_id = user.id

    id_token = _make_id_token(
        sub="ak-sub-link-1",
        preferred_username="oidc_user",
        groups=["ktm-admin"],
    )
    fake = _FakeAsyncClient(token_body={"id_token": id_token, "access_token": "at"})

    with patch("app.services.oidc_auth_service.httpx.AsyncClient", return_value=fake):
        response = await client.post(
            "/api/auth/oidc/callback",
            json={
                "code": "auth-code",
                "code_verifier": "verifier",
                "redirect_uri": REDIRECT_URI,
            },
        )

    assert response.status_code == 200, response.text
    body = response.json()
    assert "access_token" in body
    assert body["token_type"] == "bearer"

    # Re-query: callback commits on request session, not this fixture session
    session.expire_all()
    row = await session.scalar(select(User).where(User.id == user_id))
    assert row is not None
    assert row.authentik_sub == "ak-sub-link-1"
    # SYNC false → MES role stays planner despite ktm-admin group
    assert row.role == UserRole.planner


@pytest.mark.asyncio
async def test_oidc_callback_links_by_authentik_sub(
    client, session, oidc_enabled
) -> None:
    """Primary link: match by authentik_sub even if username differs."""
    user = User(
        username="linked_already",
        email="linked@example.com",
        password_hash=get_password_hash("password123"),
        full_name="Linked User",
        role=UserRole.viewer,
        is_active=True,
        authentik_sub="ak-sub-known",
    )
    session.add(user)
    await session.commit()

    id_token = _make_id_token(
        sub="ak-sub-known",
        preferred_username="other_name_not_local",
        email="other@example.com",
    )
    fake = _FakeAsyncClient(token_body={"id_token": id_token, "access_token": "at"})

    with patch("app.services.oidc_auth_service.httpx.AsyncClient", return_value=fake):
        response = await client.post(
            "/api/auth/oidc/callback",
            json={
                "code": "c",
                "code_verifier": "v",
                "redirect_uri": REDIRECT_URI,
            },
        )

    assert response.status_code == 200, response.text
    body = response.json()
    assert body.get("username") == "linked_already" or "access_token" in body


@pytest.mark.asyncio
async def test_oidc_callback_no_local_user_403(client, session, oidc_enabled) -> None:
    id_token = _make_id_token(preferred_username="missing_user", email="missing@example.com")
    fake = _FakeAsyncClient(token_body={"id_token": id_token, "access_token": "at"})

    with patch("app.services.oidc_auth_service.httpx.AsyncClient", return_value=fake):
        response = await client.post(
            "/api/auth/oidc/callback",
            json={
                "code": "auth-code",
                "code_verifier": "verifier",
                "redirect_uri": REDIRECT_URI,
            },
        )

    assert response.status_code == 403
    assert response.json()["detail"] == "oidc_user_not_linked"


@pytest.mark.asyncio
async def test_oidc_callback_sync_role_when_flag_on(
    client, session, oidc_enabled
) -> None:
    """Opt-in: AUTH_OIDC_SYNC_ROLE_FROM_IDP overwrites users.role from groups."""
    settings.AUTH_OIDC_SYNC_ROLE_FROM_IDP = True
    user = User(
        username="oidc_sync_role",
        email="oidc_sync@example.com",
        password_hash=get_password_hash("password123"),
        full_name="Sync Role User",
        role=UserRole.viewer,
        is_active=True,
    )
    session.add(user)
    await session.commit()
    user_id = user.id

    id_token = _make_id_token(
        sub="ak-sub-sync-role",
        preferred_username="oidc_sync_role",
        groups=["ktm-admin"],
    )
    fake = _FakeAsyncClient(token_body={"id_token": id_token, "access_token": "at"})

    with patch("app.services.oidc_auth_service.httpx.AsyncClient", return_value=fake):
        response = await client.post(
            "/api/auth/oidc/callback",
            json={
                "code": "auth-code-sync",
                "code_verifier": "verifier-sync",
                "redirect_uri": REDIRECT_URI,
            },
        )

    assert response.status_code == 200, response.text
    session.expire_all()
    row = await session.scalar(select(User).where(User.id == user_id))
    assert row is not None
    assert row.role == UserRole.admin
    assert row.authentik_sub == "ak-sub-sync-role"


@pytest.mark.asyncio
async def test_oidc_callback_invalid_token_exchange_401(client, oidc_enabled) -> None:
    fake = _FakeAsyncClient(token_body=None, token_status=400)

    with patch("app.services.oidc_auth_service.httpx.AsyncClient", return_value=fake):
        response = await client.post(
            "/api/auth/oidc/callback",
            json={
                "code": "bad",
                "code_verifier": "verifier",
                "redirect_uri": REDIRECT_URI,
            },
        )

    assert response.status_code == 401
    assert response.json()["detail"] == "invalid_oidc_code"


@pytest.mark.asyncio
async def test_oidc_url_resolution(oidc_enabled) -> None:
    assert "authorize" in OidcAuthService.resolve_authorization_url()
    assert "token" in OidcAuthService.resolve_token_url()
    assert "jwks" in OidcAuthService.resolve_jwks_url()
    assert "end-session" in OidcAuthService.resolve_end_session_url()


@pytest.mark.asyncio
async def test_oidc_issuer_candidates_include_aliases(oidc_enabled) -> None:
    settings.AUTH_OIDC_ISSUER_ALIASES = "192.168.1.10,host.docker.internal"
    candidates = OidcAuthService._issuer_candidates()
    joined = " ".join(candidates)
    assert "localhost" in joined
    assert "192.168.1.10" in joined
    assert "host.docker.internal" in joined
    assert "ktm2000" in joined


@pytest.mark.asyncio
async def test_oidc_issuer_accepts_lan_iss(client, session, oidc_enabled) -> None:
    """id_token.iss with LAN host (alias) must validate against primary issuer."""
    settings.AUTH_OIDC_ISSUER_ALIASES = "192.168.1.50"
    user = User(
        username="lan_iss_user",
        email="lan_iss@example.com",
        password_hash=get_password_hash("password123"),
        full_name="LAN ISS",
        role=UserRole.viewer,
        is_active=True,
        authentik_sub="ak-sub-lan",
    )
    session.add(user)
    await session.commit()

    lan_iss = "http://192.168.1.50:9000/application/o/ktm2000"
    id_token = _make_id_token(
        sub="ak-sub-lan",
        preferred_username="lan_iss_user",
        iss=lan_iss,
    )
    fake = _FakeAsyncClient(token_body={"id_token": id_token, "access_token": "at"})

    with patch("app.services.oidc_auth_service.httpx.AsyncClient", return_value=fake):
        response = await client.post(
            "/api/auth/oidc/callback",
            json={
                "code": "c",
                "code_verifier": "v",
                "redirect_uri": REDIRECT_URI,
            },
        )

    assert response.status_code == 200, response.text
