import { useState, useEffect, useRef, type FormEvent } from "react"
import { Navigate, useSearchParams } from "react-router-dom"
import { Loader2, Eye, EyeOff, Shield } from "lucide-react"
import { useAuth } from "../hooks/useAuth"
import { getErrorMessage } from "@/shared/api/client"
import { verifyOTPProfileApi, setupPasswordWithOTPApi } from "../api"
import {
  fetchOidcConfig,
  startOidcLogin,
  type OidcConfig,
} from "../api/oidcAuth"


/**
 * Страница входа в систему KTM-2000.
 * Dual-run SSO: OIDC on → stub auto-redirect to Authentik; escape via /login?password=1.
 */
export function LoginPage() {
  const { login, loginWithOTP, loginWithToken, isAuthenticated, isLoading: authLoading } = useAuth()
  const [searchParams] = useSearchParams()

  const [loginMethod, setLoginMethod] = useState<"password" | "otp">("password")
  const [username, setUsername] = useState("")
  const [password, setPassword] = useState("")
  const [otpToken, setOtpToken] = useState("")
  const [showPassword, setShowPassword] = useState(false)
  const [error, setError] = useState("")
  const [isSubmitting, setIsSubmitting] = useState(false)
  const [shake, setShake] = useState(false)

  // OTP two-step: code → optional setup-password
  const [otpStep, setOtpStep] = useState<"code" | "setup-password">("code")
  const [otpUserInfo, setOtpUserInfo] = useState<{ username: string; full_name: string } | null>(null)
  const [newPassword, setNewPassword] = useState("")
  const [confirmPassword, setConfirmPassword] = useState("")

  // OIDC dual-run
  const [oidcConfig, setOidcConfig] = useState<OidcConfig | null>(null)
  const [oidcLoaded, setOidcLoaded] = useState(false)
  const [oidcStarting, setOidcStarting] = useState(false)
  const oidcAutoStartedRef = useRef(false)

  const forceFullForm =
    searchParams.get("password") === "1" ||
    import.meta.env.VITE_SSO_STUB === "false"
  const oidcEnabled = Boolean(
    oidcConfig?.enabled &&
      oidcConfig.authorization_url &&
      oidcConfig.client_id
  )
  const ssoStubActive = oidcLoaded && oidcEnabled && !forceFullForm

  const resetOTPStates = () => {
    setOtpStep("code")
    setOtpUserInfo(null)
    setNewPassword("")
    setConfirmPassword("")
  }

  const otpInputRef = useRef<HTMLInputElement>(null)

  useEffect(() => {
    if (loginMethod === "otp" && otpStep === "code") {
      const timer = setTimeout(() => {
        otpInputRef.current?.focus()
      }, 50)
      return () => clearTimeout(timer)
    }
  }, [loginMethod, otpStep])

  useEffect(() => {
    let cancelled = false
    async function loadOidc() {
      try {
        const oidc = await fetchOidcConfig()
        if (!cancelled) setOidcConfig(oidc)
      } catch {
        if (!cancelled) setOidcConfig(null)
      } finally {
        if (!cancelled) setOidcLoaded(true)
      }
    }
    void loadOidc()
    return () => {
      cancelled = true
    }
  }, [])

  async function handleOidcLogin() {
    if (!oidcConfig || !oidcEnabled) return
    setError("")
    setOidcStarting(true)
    try {
      await startOidcLogin(oidcConfig)
    } catch (err: unknown) {
      setError(err instanceof Error ? err.message : "Ошибка входа через единый вход")
      setOidcStarting(false)
    }
  }

  // Stub mode: auto-redirect to Authentik once (ref guard)
  useEffect(() => {
    if (!ssoStubActive || !oidcConfig || oidcAutoStartedRef.current) return
    if (authLoading || isAuthenticated) return
    oidcAutoStartedRef.current = true
    void handleOidcLogin()
    // eslint-disable-next-line react-hooks/exhaustive-deps -- once on stub activation
  }, [ssoStubActive, oidcConfig, authLoading, isAuthenticated])

  // Если идет проверка авторизации
  if (authLoading) {
    return (
      <div className="flex h-screen w-full items-center justify-center bg-slate-50">
        <Loader2 className="h-8 w-8 animate-spin text-slate-500" />
      </div>
    )
  }

  if (isAuthenticated) {
    return <Navigate to="/" replace />
  }

  // SSO stub pending / redirecting
  if (ssoStubActive || (!forceFullForm && !oidcLoaded)) {
    return (
      <div className="flex min-h-screen flex-col items-center justify-center gap-4 bg-slate-50 p-4">
        <img
          src="/logo.svg"
          alt="KTM-2000"
          className="h-14 w-14 rounded-2xl shadow-lg shadow-slate-900/15"
          width={56}
          height={56}
        />
        <div className="flex items-center gap-2 text-slate-600">
          <Loader2 className="h-5 w-5 animate-spin text-slate-500" />
          <p className="text-sm">
            {oidcStarting || ssoStubActive
              ? "Переход к единому входу…"
              : "Проверка настроек входа…"}
          </p>
        </div>
        {error && (
          <div className="w-full max-w-md rounded-lg border border-red-200 bg-red-50 px-4 py-2.5 text-sm text-red-600">
            {error}
          </div>
        )}
        <a
          href="/login?password=1"
          className="text-xs text-slate-400 underline-offset-2 hover:text-slate-600 hover:underline"
        >
          Войти с паролем или кодом
        </a>
      </div>
    )
  }

  const handleSubmit = async (e: FormEvent) => {
    e.preventDefault()
    setError("")
    setIsSubmitting(true)

    try {
      if (loginMethod === "password") {
        await login(username, password)
      } else {
        if (otpStep === "code") {
          if (!otpToken || otpToken.length !== 6) {
            throw new Error("Код входа должен состоять из 6 цифр")
          }
          const profile = await verifyOTPProfileApi(otpToken)
          if (profile.is_password_set) {
            await loginWithOTP(otpToken)
          } else {
            setOtpUserInfo(profile)
            setOtpStep("setup-password")
          }
        } else {
          if (!newPassword) {
            throw new Error("Пароль обязателен")
          }
          if (newPassword !== confirmPassword) {
            throw new Error("Пароли не совпадают")
          }
          if (newPassword.length < 4) {
            throw new Error("Пароль должен быть не менее 4 символов")
          }
          const { access_token } = await setupPasswordWithOTPApi(otpToken, newPassword)
          await loginWithToken(access_token)
        }
      }
    } catch (err) {
      const msg = getErrorMessage(err)
      setError(msg)
      setShake(true)
      setTimeout(() => setShake(false), 600)
    } finally {
      setIsSubmitting(false)
    }
  }

  return (
    <div className="relative flex min-h-screen items-center justify-center overflow-hidden bg-slate-50">
      <div className="absolute -left-40 -top-40 h-80 w-80 rounded-full bg-blue-500/5 blur-3xl" />
      <div className="absolute -bottom-40 -right-40 h-96 w-96 rounded-full bg-indigo-500/5 blur-3xl" />

      <div
        className={`relative z-10 w-full max-w-md px-4 transition-transform ${
          shake ? "animate-[shake_0.5s_ease-in-out]" : ""
        }`}
      >
        <div className="rounded-2xl border border-slate-200 bg-white p-8 shadow-xl shadow-slate-100 sm:p-10">
          <div className="mb-8 flex flex-col items-center gap-3">
            <img
              src="/logo.svg"
              alt="KTM-2000"
              className="h-14 w-14 rounded-2xl shadow-lg shadow-slate-900/15"
              width={56}
              height={56}
            />
            <div className="text-center">
              <h1 className="text-2xl font-bold tracking-tight text-slate-900">KTM-2000</h1>
              <p className="mt-1 text-sm text-slate-500">Система планирования производства</p>
            </div>
          </div>

          {/* SSO button when OIDC enabled and full form forced */}
          {oidcEnabled && forceFullForm && (
            <div className="mb-5 space-y-3">
              <button
                type="button"
                disabled={isSubmitting || oidcStarting}
                onClick={() => void handleOidcLogin()}
                className="flex w-full items-center justify-center gap-2 rounded-lg border border-slate-300 bg-white px-4 py-2.5 text-sm font-semibold text-slate-800 shadow-sm transition-all hover:bg-slate-50 disabled:opacity-60"
              >
                {oidcStarting ? (
                  <Loader2 className="h-4 w-4 animate-spin" />
                ) : (
                  <Shield className="h-4 w-4 text-indigo-600" />
                )}
                {oidcStarting ? "Переход…" : "Единый вход (SSO)"}
              </button>
              <div className="flex items-center gap-3 text-xs text-slate-400">
                <div className="h-px flex-1 bg-slate-200" />
                <span>или локальный вход</span>
                <div className="h-px flex-1 bg-slate-200" />
              </div>
            </div>
          )}

          <div className="mb-6 flex rounded-lg bg-slate-100 p-1">
            <button
              type="button"
              onClick={() => { setLoginMethod("password"); setError(""); resetOTPStates(); }}
              className={`flex-1 rounded-md py-2 text-center text-xs font-medium transition-all duration-200 ${
                loginMethod === "password"
                  ? "bg-white text-slate-900 shadow-sm"
                  : "text-slate-500 hover:text-slate-900"
              }`}
            >
              Обычный вход
            </button>
            <button
              type="button"
              onClick={() => { setLoginMethod("otp"); setError(""); resetOTPStates(); }}
              className={`flex-1 rounded-md py-2 text-center text-xs font-medium transition-all duration-200 ${
                loginMethod === "otp"
                  ? "bg-white text-slate-900 shadow-sm"
                  : "text-slate-500 hover:text-slate-900"
              }`}
            >
              Вход по коду
            </button>
          </div>

          <form onSubmit={handleSubmit} className="space-y-5">
            {loginMethod === "password" ? (
              <>
                <div className="space-y-2">
                  <label htmlFor="login-username" className="block text-sm font-medium text-slate-700">
                    Имя пользователя или Email
                  </label>
                  <input
                    id="login-username"
                    type="text"
                    autoComplete="username"
                    required
                    value={username}
                    onChange={(e) => setUsername(e.target.value)}
                    className="block w-full rounded-lg border border-slate-300 bg-white px-4 py-2.5 text-sm text-slate-900 shadow-sm outline-none transition-all duration-200 hover:border-slate-400 focus:border-blue-600 focus:ring-4 focus:ring-blue-600/10"
                  />
                </div>

                <div className="space-y-2">
                  <label htmlFor="login-password" className="block text-sm font-medium text-slate-700">
                    Пароль
                  </label>
                  <div className="relative">
                    <input
                      id="login-password"
                      type={showPassword ? "text" : "password"}
                      autoComplete="current-password"
                      required
                      value={password}
                      onChange={(e) => setPassword(e.target.value)}
                      className="block w-full rounded-lg border border-slate-300 bg-white px-4 py-2.5 pr-10 text-sm text-slate-900 shadow-sm outline-none transition-all duration-200 hover:border-slate-400 focus:border-blue-600 focus:ring-4 focus:ring-blue-600/10"
                    />
                    <button
                      type="button"
                      onClick={() => setShowPassword((v) => !v)}
                      tabIndex={-1}
                      className="absolute right-3 top-1/2 -translate-y-1/2 text-slate-400 transition-colors hover:text-slate-600"
                    >
                      {showPassword ? <EyeOff className="h-4 w-4" /> : <Eye className="h-4 w-4" />}
                    </button>
                  </div>
                </div>
              </>
            ) : otpStep === "code" ? (
              <div className="space-y-2">
                <label htmlFor="login-otp" className="block text-sm font-medium text-slate-700 text-center">
                  Одноразовый 6-значный код входа
                </label>
                <input
                  id="login-otp"
                  ref={otpInputRef}
                  type="text"
                  maxLength={6}
                  placeholder="••••••"
                  required
                  value={otpToken}
                  onChange={(e) => setOtpToken(e.target.value.replace(/\D/g, ""))}
                  className="block w-full text-center tracking-[0.5em] text-xl font-bold rounded-lg border border-slate-300 bg-white px-4 py-2.5 shadow-sm outline-none transition-all duration-200 hover:border-slate-400 focus:border-blue-600 focus:ring-4 focus:ring-blue-600/10"
                />
              </div>
            ) : (
              <div className="space-y-4">
                <div className="rounded-lg bg-blue-50/50 p-3 text-center border border-blue-100">
                  <p className="text-xs text-blue-600 font-medium uppercase tracking-wider">Активация профиля</p>
                  <p className="text-sm font-semibold text-slate-900 mt-1">{otpUserInfo?.full_name}</p>
                  <p className="text-xs text-slate-500 mt-0.5">Логин: @{otpUserInfo?.username}</p>
                </div>
                <div className="space-y-2">
                  <label htmlFor="setup-password" className="block text-sm font-medium text-slate-700">
                    Придумайте пароль
                  </label>
                  <input
                    id="setup-password"
                    type="password"
                    required
                    value={newPassword}
                    onChange={(e) => setNewPassword(e.target.value)}
                    className="block w-full rounded-lg border border-slate-300 bg-white px-4 py-2.5 text-sm text-slate-900 shadow-sm outline-none transition-all duration-200 hover:border-slate-400 focus:border-blue-600 focus:ring-4 focus:ring-blue-600/10"
                  />
                </div>
                <div className="space-y-2">
                  <label htmlFor="confirm-password" className="block text-sm font-medium text-slate-700">
                    Подтвердите пароль
                  </label>
                  <input
                    id="confirm-password"
                    type="password"
                    required
                    value={confirmPassword}
                    onChange={(e) => setConfirmPassword(e.target.value)}
                    className="block w-full rounded-lg border border-slate-300 bg-white px-4 py-2.5 text-sm text-slate-900 shadow-sm outline-none transition-all duration-200 hover:border-slate-400 focus:border-blue-600 focus:ring-4 focus:ring-blue-600/10"
                  />
                </div>
              </div>
            )}

            {error && (
              <div className="rounded-lg border border-red-200 bg-red-50 px-4 py-2.5 text-sm text-red-600">
                {error}
              </div>
            )}

            <button
              type="submit"
              disabled={isSubmitting}
              className="flex w-full items-center justify-center gap-2 rounded-lg bg-blue-600 px-4 py-2.5 text-sm font-semibold text-white shadow-md shadow-blue-600/10 transition-all duration-200 hover:bg-blue-700 hover:shadow-lg focus:outline-none focus:ring-2 focus:ring-blue-500/50 focus:ring-offset-2 focus:ring-offset-white disabled:cursor-not-allowed disabled:opacity-60"
            >
              {isSubmitting && <Loader2 className="h-4 w-4 animate-spin" />}
              {isSubmitting
                ? "Обработка..."
                : loginMethod === "password"
                ? "Войти"
                : otpStep === "code"
                ? "Продолжить"
                : "Сохранить пароль и войти"}
            </button>

            {loginMethod === "otp" && otpStep === "setup-password" && (
              <button
                type="button"
                onClick={resetOTPStates}
                className="mt-2 w-full text-center text-xs text-slate-500 hover:text-slate-800 transition-colors"
              >
                Вернуться к вводу кода
              </button>
            )}
          </form>
        </div>

        <p className="mt-6 text-center text-xs text-slate-400">
          KTM-2000 · Планирование производства
        </p>
      </div>

      <style>{`
        @keyframes shake {
          0%, 100% { transform: translateX(0); }
          10%, 30%, 50%, 70%, 90% { transform: translateX(-4px); }
          20%, 40%, 60%, 80% { transform: translateX(4px); }
        }
      `}</style>
    </div>
  )
}
