import { useState, useEffect, useRef, type FormEvent } from "react"
import { Navigate } from "react-router-dom"
import { Factory, Loader2, Eye, EyeOff } from "lucide-react"
import { useAuth } from "../hooks/useAuth"
import { getErrorMessage } from "@/shared/api/client"
import { verifyOTPProfileApi, setupPasswordWithOTPApi } from "../api"


/**
 * Страница входа в систему KTM-2000.
 * Современная светлая тема, центрированная карточка.
 */
export function LoginPage() {
  const { login, loginWithOTP, loginWithToken, isAuthenticated, isLoading: authLoading } = useAuth()

  const [loginMethod, setLoginMethod] = useState<"password" | "otp">("password")
  const [username, setUsername] = useState("")
  const [password, setPassword] = useState("")
  const [otpToken, setOtpToken] = useState("")
  const [showPassword, setShowPassword] = useState(false)
  const [error, setError] = useState("")
  const [isSubmitting, setIsSubmitting] = useState(false)
  const [shake, setShake] = useState(false)

  // Новые состояния для двухэтапного входа по OTP и активации профиля
  const [otpStep, setOtpStep] = useState<"code" | "setup-password">("code")
  const [otpUserInfo, setOtpUserInfo] = useState<{ username: string; full_name: string } | null>(null)
  const [newPassword, setNewPassword] = useState("")
  const [confirmPassword, setConfirmPassword] = useState("")

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
            // Если пароль уже задан — логинимся по OTP сразу
            await loginWithOTP(otpToken)
          } else {
            // Иначе — открываем форму создания пароля
            setOtpUserInfo(profile)
            setOtpStep("setup-password")
          }
        } else {
          // Шаг установки пароля
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
      // Анимация «тряски» при ошибке
      setShake(true)
      setTimeout(() => setShake(false), 600)
    } finally {
      setIsSubmitting(false)
    }
  }

  return (
    <div className="relative flex min-h-screen items-center justify-center overflow-hidden bg-slate-50">
      {/* Декоративные фоновые элементы для легкого премиального эффекта */}
      <div className="absolute -left-40 -top-40 h-80 w-80 rounded-full bg-blue-500/5 blur-3xl" />
      <div className="absolute -bottom-40 -right-40 h-96 w-96 rounded-full bg-indigo-500/5 blur-3xl" />

      {/* Карточка входа */}
      <div
        className={`relative z-10 w-full max-w-md px-4 transition-transform ${
          shake ? "animate-[shake_0.5s_ease-in-out]" : ""
        }`}
      >
        <div className="rounded-2xl border border-slate-200 bg-white p-8 shadow-xl shadow-slate-100 sm:p-10">
          {/* Лого и заголовок */}
          <div className="mb-8 flex flex-col items-center gap-3">
            <div className="flex h-14 w-14 items-center justify-center rounded-2xl bg-gradient-to-br from-blue-600 to-indigo-600 shadow-lg shadow-blue-600/20">
              <Factory className="h-7 w-7 text-white" />
            </div>
            <div className="text-center">
              <h1 className="text-2xl font-bold tracking-tight text-slate-900">KTM-2000</h1>
              <p className="mt-1 text-sm text-slate-500">Система планирования производства</p>
            </div>
          </div>

          {/* Переключатель вкладок входа */}
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

          {/* Форма */}
          <form onSubmit={handleSubmit} className="space-y-5">
            {loginMethod === "password" ? (
              <>
                {/* Username / Login */}
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

                {/* Password */}
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
              /* OTP Token */
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
              /* Установка пароля (Активация профиля) */
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

            {/* Ошибка */}
            {error && (
              <div className="rounded-lg border border-red-200 bg-red-50 px-4 py-2.5 text-sm text-red-600">
                {error}
              </div>
            )}

            {/* Кнопка входа */}
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

            {/* Ссылка возврата на первый шаг для OTP */}
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

        {/* Подпись снизу */}
        <p className="mt-6 text-center text-xs text-slate-400">
          KTM-2000 · Планирование производства
        </p>
      </div>

      {/* CSS-анимация shake */}
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
