import { apiClient } from "@/shared/api/client"

/** Роли пользователей в системе */
export type UserRole = "admin" | "planner" | "section_manager" | "operator" | "viewer" | "transporter"

/** Данные пользователя, получаемые из /auth/me */
export interface User {
  id: number
  username: string
  email: string
  full_name: string
  role: UserRole
  section_id: number | null
  section_ids: number[]
  is_active: boolean
  tab_number?: string | null
  /** Multiavatar seed — cache of IdP attributes.profile_avatar_seed */
  avatar_seed?: string | null
  locale?: string | null
  theme?: string | null
  authentik_linked?: boolean
  profile_sot?: "authentik" | "local" | string
  /** Аварийный (Break Glass) вход — эфемерная учётка без записи в БД. */
  is_break_glass?: boolean
}

/**
 * Получение данных текущего авторизованного пользователя.
 * `force=true` → ?refresh=1 — принудительный pull из IdP, обходя TTL-кэш
 * бэкенда (аватар/ФИО/email из Authentik обновляются мгновенно).
 */
export async function fetchMeApi(force = false): Promise<User> {
  const { data } = await apiClient.get<User>(force ? "/auth/me?refresh=1" : "/auth/me")
  return data
}

/** Роль в справочнике /auth/roles: код, подпись и допустимые разделы навигации */
export interface RoleSections {
  code: UserRole
  label: string
  sections: string[]
}

/** Ответ сервера на запрос GET /auth/roles */
export interface RolesResponse {
  roles: RoleSections[]
}

/** Справочник ролей: коды, подписи и допустимые разделы навигации (источник правды — сервер) */
export async function fetchRolesApi(): Promise<RolesResponse> {
  const { data } = await apiClient.get<RolesResponse>("/auth/roles")
  return data
}

/** Server revoke current session (best-effort before local clear). */
export async function logoutApi(): Promise<void> {
  await apiClient.post("/auth/logout")
}

