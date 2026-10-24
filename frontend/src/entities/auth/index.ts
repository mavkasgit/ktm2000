/**
 * Публичная точка входа auth-ядра (FSD entities).
 *
 * Здесь живёт всё, что нужно другим фичам и слою app: контекст/провайдер
 * авторизации, права, политики, типы пользователя и OIDC-клиент. Фича
 * `features/auth` оставлена только для страниц и компонентов входа и сама
 * импортирует отсюда.
 */
export { AUTH_SHELL_VERSION, AuthProvider, useAuth } from "./hooks/useAuth"
export type { AuthShellUser } from "./hooks/useAuth"

export { usePermission } from "./hooks/usePermission"
export type { UsePermissionResult } from "./hooks/usePermission"

export { POLICIES } from "./policies"

export type { User, UserRole } from "./api"

export {
  clearAppAuthTokens,
  clearOidcReloginGuard,
  clearPkce,
  completeOidcCallback,
  fetchOidcConfig,
  mapIdpRedirectError,
  OIDC_ERROR_CODES,
  OidcAuthError,
  resolveOidcErrorText,
  startOidcLogin,
  tryForceOidcRelogin,
} from "./oidc/oidcAuth"
export type { OidcConfig, OidcDisplayInfo, OidcErrorInfo } from "./oidc/oidcAuth"
export { oidcHostConfig } from "./oidc/oidcHostConfig"
