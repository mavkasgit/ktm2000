import { createContext, useContext, useState, useEffect, useCallback, type ReactNode } from "react"
import { loginApi, fetchMeApi, loginWithOTPApi, type User } from "../api"

const TOKEN_KEY = "ktm2000_token"

interface AuthContextValue {
  user: User | null
  isAuthenticated: boolean
  isLoading: boolean
  login: (username: string, password: string) => Promise<void>
  loginWithOTP: (token: string) => Promise<void>
  loginWithToken: (accessToken: string) => Promise<void>
  logout: () => void
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

  const login = useCallback(async (username: string, password: string) => {
    const { access_token } = await loginApi(username, password)
    localStorage.setItem(TOKEN_KEY, access_token)
    document.cookie = `ktm2000_token=${access_token}; path=/; max-age=86400; SameSite=Lax`
    const me = await fetchMeApi()
    setUser(me)
  }, [])

  const loginWithOTP = useCallback(async (token: string) => {
    const { access_token } = await loginWithOTPApi(token)
    localStorage.setItem(TOKEN_KEY, access_token)
    document.cookie = `ktm2000_token=${access_token}; path=/; max-age=86400; SameSite=Lax`
    const me = await fetchMeApi()
    setUser(me)
  }, [])

  const loginWithToken = useCallback(async (accessToken: string) => {
    localStorage.setItem(TOKEN_KEY, accessToken)
    document.cookie = `ktm2000_token=${accessToken}; path=/; max-age=86400; SameSite=Lax`
    const me = await fetchMeApi()
    setUser(me)
  }, [])

  const logout = useCallback(() => {
    localStorage.removeItem(TOKEN_KEY)
    document.cookie = "ktm2000_token=; path=/; max-age=0"
    setUser(null)
    window.location.href = "/login"
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
