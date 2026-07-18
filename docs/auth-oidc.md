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
  → BE: token exchange + JWKS id_token → link User → app JWT (HS256)
  → localStorage/cookie ktm2000_token
```

API всегда принимает **app JWT**, не IdP access_token.

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

1. FE `useAuth.logout`: clear `ktm2000_token` (localStorage + cookie)
2. Если OIDC on: `GET /api/auth/oidc/logout-url` → redirect `logout_url` (Authentik end-session → `/login`)
3. Иначе: `window.location = /login`
4. Server session revoke (`user_sessions` + JWT `sid`) — **фаза W4**, пока нет

## Endpoints

| Method | Path | Auth |
|--------|------|------|
| GET | `/api/auth/oidc/config` | public |
| POST | `/api/auth/oidc/callback` | public |
| GET | `/api/auth/oidc/logout-url` | public |
| POST | `/api/auth/login` | public |
| GET | `/api/auth/me` | Bearer |
| OTP | `/api/auth/otp/*` | dual-run |

## Env (ключевые)

См. полный набор в [`.env.example`](../.env.example).

| Key | Default | Notes |
|-----|---------|-------|
| `AUTH_OIDC_ENABLED` | `false` | dual-run switch |
| `AUTH_OIDC_ISSUER` | — | `…/application/o/ktm2000/` |
| `AUTH_OIDC_CLIENT_ID` | — | public client `ktm2000` |
| `AUTH_OIDC_REDIRECT_URI` | — | :5180 / :8082 `/auth/callback` |
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
| Model | `backend/app/models/user.py` (`authentik_sub`) |
| Migration | `backend/alembic/versions/013_users_authentik_sub.py` |
| FE auth | `frontend/src/features/auth/hooks/useAuth.tsx` |
| FE OIDC | `frontend/src/features/auth/api/oidcAuth.ts` |
| Tests | `backend/tests/test_auth_oidc.py`, `test_auth.py` |
