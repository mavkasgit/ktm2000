/**
 * Хостовый конфиг OIDC-модуля (KTM-2000).
 *
 * Бренд-специфичные значения для общего OIDC-кода (oidcAuth.ts /
 * OidcCallbackPage.tsx): storage-префикс, token-ключ, cookie-ключ, scope,
 * имя приложения, apiBase и словарь RU-текстов ошибок (машинный code → текст).
 *
 * Файл хостовый: содержимое может отличаться между проектами (HRMS / KTM),
 * в scripts/sync-manifest.json не входит. Версия модуля дублируется здесь,
 * в oidcAuth.ts и OidcCallbackPage.tsx — по ней verify-sync сверяет общий код.
 */
import { API_BASE_URL } from "@/shared/api/client"

/** Версия OIDC-модуля — синхронизируется verify-sync (режим content + version). */
export const OIDC_MODULE_VERSION = "1.0.0"

export type OidcErrorText = {
  title: string
  message: string
  /** Добавить сырой detail бэкенда/IdP к message (для fallback-ошибок). */
  withDetail?: boolean
}

export type OidcHostConfig = {
  /** Префикс storage-ключей OIDC (localStorage/sessionStorage). */
  storagePrefix: string
  /** Ключ app-токена в localStorage. */
  tokenKey: string
  /** Кука app-токена; null — куки не пишем и не чистим. */
  cookieKey: string | null
  /** Default scope для authorize-запроса, если сервер не прислал свой. */
  scope: string
  /** Имя приложения (для alt/aria и бренд-текстов). */
  appName: string
  /** Базовый URL API (без trailing slash). */
  apiBase: string
  /** Словарь машинных кодов ошибок OIDC → RU-текст. */
  errorText: Record<string, OidcErrorText>
}

export const oidcHostConfig: OidcHostConfig = {
  storagePrefix: "ktm2000",
  tokenKey: "ktm2000_token",
  cookieKey: "ktm2000_token",
  scope: "openid profile email",
  appName: "KTM-2000",
  apiBase: API_BASE_URL,
  errorText: {
    OIDC_LOGIN_UNAVAILABLE: {
      title: "Единый вход недоступен",
      message: "Вход через единый вход недоступен",
    },
    OIDC_PKCE_MISSING: {
      title: "Сессия входа истекла",
      message:
        "Не найден code_verifier (PKCE). Так бывает, если закрыли вкладку, сменили браузер " +
        "или открыли callback без старта с /login. Начните вход заново с страницы входа KTM-2000.",
    },
    OIDC_INVALID_STATE: {
      title: "Ошибка проверки state",
      message:
        "Параметр state не совпал с сохранённым — возможна подмена или устаревшая вкладка. " +
        "Начните вход заново.",
    },
    OIDC_MISSING_CODE: {
      title: "Нет кода авторизации",
      message:
        "В адресе возврата нет параметра code. Начните вход с страницы входа KTM-2000 заново " +
        "(не открывайте /auth/callback вручную).",
    },
    OIDC_MISSING_ACCESS_TOKEN: {
      title: "Нет токена доступа",
      message: "Сервер KTM не вернул access_token после обмена кода. Попробуйте войти снова.",
    },
    OIDC_EXCHANGE_FAILED: {
      title: "Не удалось войти",
      message: "Не удалось завершить вход через единый вход. Попробуйте снова.",
      withDetail: true,
    },
    OIDC_UNKNOWN: {
      title: "Не удалось войти",
      message: "Неизвестная ошибка при завершении единого входа.",
      withDetail: true,
    },
    oidc_user_not_linked: {
      title: "Нет учётной записи в KTM-2000",
      message:
        "Вход в единый IdP прошёл успешно, но этот пользователь не привязан к KTM-2000. " +
        "Обратитесь к администратору: нужно создать пользователя с тем же логином/email " +
        "либо включить автосоздание (JIT).",
    },
    no_access: {
      title: "Нет доступа",
      message:
        "Учётная запись есть, но нет роли доступа. Обратитесь к администратору KTM-2000.",
    },
    invalid_oidc_code: {
      title: "Код входа недействителен",
      message:
        "Код авторизации от IdP истёк или уже использован. Закройте вкладку и начните вход заново.",
    },
    invalid_id_token: {
      title: "Ошибка проверки токена IdP",
      message:
        "Не удалось проверить id_token (ключ, подпись или срок). Проверьте issuer/JWKS и время на серверах.",
    },
    oidc_token_error: {
      title: "IdP не выдал токен",
      message:
        "Обмен кода на токен не удался. Проверьте client_id, redirect_uri, PKCE и grant_types у приложения OIDC.",
    },
    oidc_disabled: {
      title: "Единый вход выключен",
      message: "OIDC отключён на сервере (AUTH_OIDC_ENABLED). Войдите с паролем или кодом.",
    },
    redirect_uri: {
      title: "Неверный адрес возврата",
      message:
        "redirect_uri не совпадает с allow-list в IdP. Должен быть точный URL, например " +
        "http://localhost:8082/auth/callback.",
    },
    oidc_config: {
      title: "SSO не настроен",
      message: "На сервере KTM не заданы параметры OIDC (issuer / client_id). Проверьте .env.",
    },
    user_disabled: {
      title: "Пользователь заблокирован",
      message: "Учётная запись в KTM-2000 отключена. Обратитесь к администратору.",
    },
    oidc_not_found: {
      title: "Единый вход недоступен",
      message: "Эндпоинт OIDC не найден или вход через IdP отключён.",
    },
    HTTP_401: {
      title: "Ошибка авторизации",
      message: "Не удалось завершить вход через единый вход. Попробуйте снова.",
      withDetail: true,
    },
    HTTP_403: {
      title: "Доступ запрещён",
      message: "Сервер отклонил вход (403). Обратитесь к администратору.",
      withDetail: true,
    },
    HTTP_5XX: {
      title: "Сервис недоступен",
      message: "IdP или API временно недоступны. Подождите и попробуйте снова.",
    },
    access_denied: {
      title: "Вход отменён",
      message: "Вы отменили вход в IdP или доступ к приложению запрещён политикой.",
      withDetail: true,
    },
    invalid_request: {
      title: "Некорректный запрос к IdP",
      message:
        "Частые причины: у OAuth-провайдера не включён grant authorization_code, " +
        "неверный redirect_uri или client_id. Проверьте настройки приложения ktm2000 в Authentik.",
      withDetail: true,
    },
    unauthorized_client: {
      title: "Клиент не разрешён",
      message:
        "IdP отклонил client_id (тип клиента, grant types или redirect). Проверьте provider KTM-2000.",
      withDetail: true,
    },
    login_required: {
      title: "Нужен повторный вход",
      message: "Сессия IdP истекла. Начните вход заново.",
      withDetail: true,
    },
    interaction_required: {
      title: "Нужен повторный вход",
      message: "Сессия IdP истекла. Начните вход заново.",
      withDetail: true,
    },
    server_error: {
      title: "Ошибка IdP",
      message: "Сервер единого входа временно недоступен. Попробуйте позже.",
      withDetail: true,
    },
    temporarily_unavailable: {
      title: "Ошибка IdP",
      message: "Сервер единого входа временно недоступен. Попробуйте позже.",
      withDetail: true,
    },
    oidc_idp_error: {
      title: "Ошибка IdP",
      message: "IdP вернул ошибку.",
      withDetail: true,
    },
  },
}
