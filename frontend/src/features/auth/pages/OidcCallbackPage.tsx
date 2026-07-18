import { useEffect, useRef, useState } from "react"
import { Loader2, AlertCircle } from "lucide-react"
import {
  completeOidcCallback,
  clearPkce,
  mapIdpRedirectError,
  OidcAuthError,
  tryForceOidcRelogin,
  type OidcErrorInfo,
} from "../api/oidcAuth"

/**
 * OIDC redirect target: /auth/callback?code=...&state=...
 * Exchanges code + PKCE verifier via backend, stores app JWT, redirects home.
 *
 * Recoverable token failures: clear local session and force IdP re-login once
 * (prompt=login) instead of a permanent error card — SPA SDK pattern.
 */
export function OidcCallbackPage() {
  const [error, setError] = useState<OidcErrorInfo | null>(null)
  const [reloginPending, setReloginPending] = useState(false)
  const started = useRef(false)

  useEffect(() => {
    if (started.current) return
    started.current = true

    async function run() {
      const params = new URLSearchParams(window.location.search)
      const err = params.get("error")
      const errDesc = params.get("error_description")
      if (err) {
        clearPkce()
        const mapped = mapIdpRedirectError(err, errDesc)
        const navigated = await tryForceOidcRelogin({
          code: err,
          httpStatus: undefined,
        })
        if (navigated) {
          setReloginPending(true)
          return
        }
        setError(mapped)
        return
      }

      const code = params.get("code")
      const state = params.get("state")
      if (!code) {
        clearPkce()
        const missing: OidcErrorInfo = {
          title: "Нет кода авторизации",
          message:
            "В адресе возврата нет параметра code. Начните вход с страницы входа KTM-2000 заново " +
            "(не открывайте /auth/callback вручную).",
          code: "missing_code",
        }
        const navigated = await tryForceOidcRelogin(missing)
        if (navigated) {
          setReloginPending(true)
          return
        }
        setError(missing)
        return
      }

      try {
        await completeOidcCallback({ code, state })
        window.location.replace("/")
      } catch (e: unknown) {
        clearPkce()
        let info: OidcErrorInfo
        if (e instanceof OidcAuthError) {
          info = {
            title: e.title,
            message: e.message,
            code: e.code,
            httpStatus: e.httpStatus,
          }
        } else if (e instanceof Error) {
          info = {
            title: "Не удалось войти",
            message: e.message,
          }
        } else {
          info = {
            title: "Не удалось войти",
            message: "Неизвестная ошибка при завершении единого входа.",
          }
        }

        const navigated = await tryForceOidcRelogin(info)
        if (navigated) {
          setReloginPending(true)
          return
        }
        setError(info)
      }
    }

    void run()
  }, [])

  if (error) {
    return (
      <div className="flex min-h-screen items-center justify-center bg-slate-50 p-4">
        <div className="w-full max-w-md space-y-4 rounded-2xl border border-slate-200 bg-white p-8 shadow-xl shadow-slate-100">
          <div className="flex items-start gap-3">
            <AlertCircle className="mt-0.5 h-5 w-5 shrink-0 text-red-600" aria-hidden />
            <div className="min-w-0 space-y-2">
              <h1 className="text-lg font-semibold text-slate-900">{error.title}</h1>
              <p className="text-sm leading-relaxed text-slate-600">{error.message}</p>
              <p className="text-sm leading-relaxed text-slate-500">
                Повторный вход не помог перезаписать токен. Войдите снова вручную или используйте
                пароль.
              </p>
              {(error.code || error.httpStatus) && (
                <p className="break-all font-mono text-xs text-slate-400">
                  {error.code ? `Код: ${error.code}` : null}
                  {error.code && error.httpStatus ? " · " : null}
                  {error.httpStatus ? `HTTP ${error.httpStatus}` : null}
                </p>
              )}
            </div>
          </div>
          <div className="flex flex-col gap-2 sm:flex-row">
            <button
              type="button"
              className="flex w-full items-center justify-center rounded-lg bg-blue-600 px-4 py-2.5 text-sm font-semibold text-white shadow-md transition-all hover:bg-blue-700"
              onClick={() => {
                window.location.href = "/login"
              }}
            >
              Войти снова
            </button>
            <button
              type="button"
              className="flex w-full items-center justify-center rounded-lg border border-slate-300 bg-white px-4 py-2.5 text-sm font-semibold text-slate-700 transition-all hover:bg-slate-50"
              onClick={() => {
                window.location.href = "/login?password=1"
              }}
            >
              Вход с паролем
            </button>
          </div>
        </div>
      </div>
    )
  }

  return (
    <div className="flex min-h-screen flex-col items-center justify-center gap-4 bg-slate-50 text-slate-600">
      <img
        src="/logo.svg"
        alt="KTM-2000"
        className="h-14 w-14 rounded-2xl shadow-lg shadow-slate-900/15"
        width={56}
        height={56}
      />
      <div className="flex items-center gap-2">
        <Loader2 className="h-5 w-5 animate-spin text-slate-500" />
        <p className="text-sm">
          {reloginPending
            ? "Требуется повторный вход — перенаправляем для обновления токена…"
            : "Завершаем вход через единый вход…"}
        </p>
      </div>
    </div>
  )
}
