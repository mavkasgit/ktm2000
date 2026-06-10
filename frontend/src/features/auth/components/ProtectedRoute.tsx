import { useEffect } from "react"
import { Navigate } from "react-router-dom"
import { Loader2 } from "lucide-react"
import { useAuth } from "../hooks/useAuth"
import { toast } from "@/shared/ui"
import type { UserRole } from "../api"
import type { ReactNode } from "react"

const ROLE_LABELS: Record<UserRole, string> = {
  admin: "Администратор",
  planner: "Планировщик",
  section_manager: "Начальник участка",
  operator: "Оператор",
  viewer: "Наблюдатель",
  transporter: "Транспортировщик",
}

interface ProtectedRouteProps {
  children: ReactNode
  /** Если указано — доступ разрешён только для перечисленных ролей */
  allowedRoles?: UserRole[]
}

/**
 * Обёртка для защищённых маршрутов.
 * - Пока идёт проверка токена — показывает спиннер.
 * - Если не авторизован — редиректит на /login.
 * - Если роль не разрешена — перенаправляет на главную и показывает уведомление.
 */
export function ProtectedRoute({ children, allowedRoles }: ProtectedRouteProps) {
  const { user, isAuthenticated, isLoading } = useAuth()

  const hasAccess = !allowedRoles || (!!user && allowedRoles.includes(user.role))

  useEffect(() => {
    if (isAuthenticated && !isLoading && !hasAccess && user) {
      const allowedNames = allowedRoles
        ? allowedRoles.map((r) => ROLE_LABELS[r]).join(", ")
        : ""
      
      toast({
        variant: "destructive",
        title: "Доступ ограничен",
        description: allowedNames
          ? `Раздел доступен только для ролей: ${allowedNames}`
          : "У вашей роли нет доступа к этой странице.",
      })
    }
  }, [isAuthenticated, isLoading, hasAccess, user, allowedRoles])

  if (isLoading) {
    return (
      <div className="flex h-screen w-full items-center justify-center">
        <Loader2 className="h-8 w-8 animate-spin text-muted-foreground" />
      </div>
    )
  }

  if (!isAuthenticated) {
    return <Navigate to="/login" replace />
  }

  if (!hasAccess) {
    return <Navigate to="/" replace />
  }

  return <>{children}</>
}
