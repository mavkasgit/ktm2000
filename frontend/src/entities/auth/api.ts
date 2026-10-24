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
}
