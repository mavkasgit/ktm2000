import { createContext, useContext, useState, useEffect, useCallback, type ReactNode } from "react"
import { loginApi, fetchMeApi, loginWithOTPApi, logoutApi, type User } from "../api"
import { fetchOidcLogoutUrl } from "../api/oidcAuth"

const TOKEN_KEY = "ktm2000_token"
/** Set before logout navigation so /login does not SSO-stub auto-redirect back into IdP. */
export const LOGGED_OUT_KEY = "ktm2000_logged_out"

interface AuthContextValue {
  user: User | null
  isAuthenticated: boolean
  isLoading: boolean
  login: (username: string, password: string) => Promise<void>
  loginWithOTP: (token: string) => Promise<void>
  loginWithToken: (accessToken: string) => Promise<void>
  logout: () => void | Promise<void>
  /** Re-fetch /auth/me (unified profile pull). */
  refreshUser: () => Promise<void>
}

const AuthContext = createContext<AuthContextValue | null>(null)

export function AuthProvider({ children }: { children: ReactNode }) {
  const [user, setUser] = useState<User | null>(null)
  const [isLoading, setIsLoading] = useState(true)

  // При монтировании проверяем наличие токена и загружаем данные пользователя
  useEffect(() => {
    const token = localStorage.getItem(TOKEN_KEY)
    if (!token) {
      setIsLoading(false)
      return
    }

    fetchMeApi()
      .then((u) => setUser(u))
      .catch(() => {
        // Если 401 или любая ошибка — очищаем токен
        localStorage.removeItem(TOKEN_KEY)
        document.cookie = "ktm2000_token=; path=/; max-age=0"
      })
      .finally(() => setIsLoading(false))
  }, [])

  const clearLoggedOutFlag = () => {
    try {
      sessionStorage.removeItem(LOGGED_OUT_KEY)
    } catch {
      /* ignore */
    }
  }

  const login = useCallback(async (username: string, password: string) => {
    const { access_token } = await loginApi(username, password)
    clearLoggedOutFlag()
    localStorage.setItem(TOKEN_KEY, access_token)
    document.cookie = `ktm2000_token=${access_token}; path=/; max-age=86400; SameSite=Lax`
    const me = await fetchMeApi()
    setUser(me)
  }, [])

  const loginWithOTP = useCallback(async (token: string) => {
    const { access_token } = await loginWithOTPApi(token)
    clearLoggedOutFlag()
    localStorage.setItem(TOKEN_KEY, access_token)
    document.cookie = `ktm2000_token=${access_token}; path=/; max-age=86400; SameSite=Lax`
    const me = await fetchMeApi()
    setUser(me)
  }, [])

  const loginWithToken = useCallback(async (accessToken: string) => {
    clearLoggedOutFlag()
    localStorage.setItem(TOKEN_KEY, accessToken)
    document.cookie = `ktm2000_token=${accessToken}; path=/; max-age=86400; SameSite=Lax`
    const me = await fetchMeApi()
    setUser(me)
  }, [])

  const refreshUser = useCallback(async () => {
    const me = await fetchMeApi()
    setUser(me)
  }, [])

  const logout = useCallback(async () => {
    // Prevent SSO stub on /login from immediately re-entering Authentik (re-login loop).
    try {
      sessionStorage.setItem(LOGGED_OUT_KEY, "1")
    } catch {
      /* ignore */
    }

    // 1) Best-effort server revoke (needs Authorization while token still present)
    try {
      await logoutApi()
    } catch {
      /* ignore — always clear local tokens */
    }
    // 2) Clear app token
    localStorage.removeItem(TOKEN_KEY)
    document.cookie = "ktm2000_token=; path=/; max-age=0"
    setUser(null)
    // 3) OIDC end-session when enabled (id_token_hint + post_logout → /login)
    try {
      const { enabled, logout_url } = await fetchOidcLogoutUrl()
      try {
        const { clearOidcIdToken } = await import("../api/oidcAuth")
        clearOidcIdToken()
      } catch {
        /* ignore */
      }
      if (enabled && logout_url) {
        window.location.assign(logout_url)
        return
      }
    } catch {
      // fall through to local /login
    }
    window.location.assign("/login")
  }, [])

  return (
    <AuthContext.Provider
      value={{
        user,
        isAuthenticated: !!user,
        isLoading,
        login,
        loginWithOTP,
        loginWithToken,
        logout,
        refreshUser,
      }}
    >
      {children}
    </AuthContext.Provider>
  )
}

/** Хук для доступа к контексту авторизации */
export function useAuth(): AuthContextValue {
  const ctx = useContext(AuthContext)
  if (!ctx) {
    throw new Error("useAuth must be used within an AuthProvider")
  }
  return ctx
}
