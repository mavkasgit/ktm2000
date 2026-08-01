import type { UserRole } from "@/features/auth/api"
import { useAuth } from "@/features/auth/hooks/useAuth"

/**
 * Подпись роли из справочника, загруженного с сервера (/auth/roles).
 * Словарь подписей больше не хранится на клиенте — единственный источник — сервер.
 */
export function useRoleLabel(role: UserRole): string {
  const { roleLabel } = useAuth()
  return roleLabel(role)
}
