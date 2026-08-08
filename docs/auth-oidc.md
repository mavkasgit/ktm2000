# Auth & OIDC (Authentik) — KTM-2000

Канон: [`.opencode/plans/authentik-unified-auth-contract.md`](../.opencode/plans/authentik-unified-auth-contract.md) (R1–R14, env §8).

## Режимы

| Режим | Условие | Поведение |
|-------|---------|-----------|
| Dual-run OIDC | `AUTH_OIDC_ENABLED=true` | FE `/login` → SSO stub → Authentik → `/auth/callback` → app JWT |
| Escape password/OTP | `/login?password=1` | Локальный password + OTP (как раньше) |
| OIDC off | `AUTH_OIDC_ENABLED=false` | Только password/OTP |
| Dev bypass | `DEV_BYPASS_AUTH=true` | Fallback `system@local`; magic Bearer `admin` **разрешён** |
| Strict/prod | `DEV_BYPASS_AUTH=false` | Только app JWT; magic `admin` → **401** |

## Flow (bridge)

```
GET /api/auth/oidc/config → PKCE S256 → Authentik authorize
  → FE /auth/callback?code&state
  → POST /api/auth/oidc/callback {code, code_verifier, redirect_uri}
  → BE: token exchange + JWKS id_token → link User → app JWT (HS256 + claim `sid`)
  → localStorage/cookie ktm2000_token
```

API всегда принимает **app JWT**, не IdP access_token.

## App sessions (`sid`)

| | |
|--|--|
| Table | `user_sessions` (id UUID PK, user_id, created_at, expires_at, revoked_at, login_method) |
| JWT claim | `sid` = `user_sessions.id` |
| Issue | password / OTP / setup-password / OIDC callback → `issue_app_token` |
| Strict check | `DEV_BYPASS_AUTH=false`: `get_current_user` requires active `sid` (missing/revoked/expired → 401) |
| Dev | `DEV_BYPASS_AUTH=true`: sid **not** required (tests mint JWT without session) |
| Logout | `POST /api/auth/logout` revokes current sid (idempotent 204) |

## Связка пользователя (link order)

1. **Primary:** `users.authentik_sub == id_token.sub`
2. **Secondary:** `preferred_username` / `email` / local-part of email (ilike) → **write** `authentik_sub` if empty
3. **JIT:** if `AUTH_OIDC_ALLOW_JIT=true` → create User with `authentik_sub`; else `403 oidc_user_not_linked`

Rename username/email не ломает link после первого OIDC-входа (sub стабилен).

## Роли (MES SoT)

- Источник правды: `users.role` (enum: admin / planner / section_manager / operator / viewer / transporter).
- IdP groups (`ktm-{role}`, `ktm2000-{role}`) — soft map **только** при `AUTH_OIDC_SYNC_ROLE_FROM_IDP=true` (default **false**).
- Не сводим MES-роли к IdP admin/viewer.

## Logout

1. Best-effort `POST /api/auth/logout` (revoke `sid` while Bearer still present).
2. Clear `ktm2000_token` (localStorage + cookie).
3. Если OIDC on: `GET /api/auth/oidc/logout-url` → Authentik end-session → `/login` → auto-SSO на Authentik login (SLO рвёт IdP-сессию).
4. `LoginPage`: всегда auto-SSO stub, когда OIDC включён и Authentik достижим; break-glass — только при недоступности IdP.
5. Успешный login / SSO — как обычно.

## Back-Channel Logout (IdP-initiated)

Authentik POSTs `logout_token` (form) на `POST /api/auth/backchannel-logout` при блокировке/логауте в IdP:

1. Валидация JWT: JWKS-подпись, `iss` (все `_issuer_candidates`), `aud=client_id`, `exp`/`iat`, `events`-claim обязателен, `nonce` запрещён (spec).
2. `sub` → `users.authentik_sub` → `revoke_sessions_for_user` (все app-сессии).
3. Unknown sub → 200 no-op; invalid token → 400 `invalid_logout_token`. IdP `sid` **не** мапится на app `sid`.

## Endpoints

| Method | Path | Auth |
|--------|------|------|
| GET | `/api/auth/oidc/config` | public |
| POST | `/api/auth/oidc/callback` | public |
| GET | `/api/auth/oidc/logout-url` | public |
| GET | `/api/auth/frontchannel-logout` | public (iframe, clears storage) |
| POST | `/api/auth/backchannel-logout` | public (Authentik form `logout_token`) |
| POST | `/api/auth/login` | public |
| POST | `/api/auth/logout` | Bearer (idempotent revoke sid) |
| GET | `/api/auth/me` | Bearer (+ active sid in strict) |
| OTP | `/api/auth/otp/*` | dual-run |

## Env (ключевые)

См. полный набор в [`.env.example`](../.env.example).

| Key | Default | Notes |
|-----|---------|-------|
| `AUTH_OIDC_ENABLED` | `false` | dual-run switch |
| `AUTH_OIDC_ISSUER` | — | `…/application/o/ktm2000/` |
| `AUTH_OIDC_CLIENT_ID` | — | public client `ktm2000` |
| `AUTH_OIDC_REDIRECT_URI` | — | :5172 / :8082 `/auth/callback` |
| `AUTH_OIDC_ISSUER_ALIASES` | — | comma hosts for multi-host `iss` |
| `AUTH_OIDC_ALLOW_JIT` | `false` | auto-create User |
| `AUTH_OIDC_DEFAULT_ROLE` | `viewer` | JIT / no group |
| `AUTH_OIDC_SYNC_ROLE_FROM_IDP` | `false` | group→role overwrite |
| `JWT_SECRET_KEY` / `SECRET_KEY` | — | **per-app**, not shared SSO (W3) |
| `DEV_BYPASS_AUTH` | `false` | system fallback + magic admin |

## Magic Bearer `admin`

- **Только** при `DEV_BYPASS_AUTH=true` (dev/test tools).
- В prod/strict (`DEV_BYPASS_AUTH=false`) → `401 Invalid or expired token`.
- Не использовать в production.

## Файлы

| Слой | Path |
|------|------|
| Config | `backend/app/core/config.py` |
| Deps | `backend/app/api/deps.py` |
| OIDC service | `backend/app/services/oidc_auth_service.py` |
| Routes | `backend/app/api/routes/auth.py` |
| Model | `backend/app/models/user.py` (`authentik_sub`), `user_session.py` |
| Sessions | `backend/app/services/session_service.py` |
| Migration | `013_users_authentik_sub`, `014_user_sessions` |
| FE auth | `frontend/src/features/auth/hooks/useAuth.tsx` |
| FE OIDC | `frontend/src/features/auth/api/oidcAuth.ts` |
| Tests | `backend/tests/test_auth_oidc.py`, `test_auth.py` |
