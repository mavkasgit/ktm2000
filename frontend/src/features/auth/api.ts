import { apiClient } from "@/shared/api/client"

/** Роли пользователей в системе */
export type UserRole = "admin" | "planner" | "section_manager" | "operator" | "viewer" | "transporter"

export interface ActiveToken {
  token: string
  session_duration_seconds: number | null
  created_at: string
}

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
  active_login_token?: ActiveToken | null
  /** Multiavatar seed — cache of IdP attributes.profile_avatar_seed */
  avatar_seed?: string | null
  locale?: string | null
  theme?: string | null
  authentik_linked?: boolean
  profile_sot?: "authentik" | "local" | string
}

export interface ProfileUpdateResponse {
  full_name: string
  avatar_seed?: string | null
  email?: string | null
  locale?: string | null
  theme?: string | null
}

/** Ответ сервера на запрос /auth/login */
export interface TokenResponse {
  access_token: string
  token_type: string
}

/** Авторизация пользователя по email/password */
export async function loginApi(username: string, password: string): Promise<TokenResponse> {
  const { data } = await apiClient.post<TokenResponse>("/auth/login", { username, password })
  return data
}

/** Получение данных текущего авторизованного пользователя */
export async function fetchMeApi(): Promise<User> {
  const { data } = await apiClient.get<User>("/auth/me")
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

/** Unified profile: name / email / locale / theme / avatar → Authentik SoT when linked */
export async function updateMyProfileApi(payload: {
  full_name?: string
  avatar_seed?: string | null
  clear_avatar?: boolean
  email?: string
  locale?: "ru" | "en"
  theme?: "system" | "light" | "dark"
}): Promise<ProfileUpdateResponse> {
  const { data } = await apiClient.patch<ProfileUpdateResponse>("/auth/me/profile", payload)
  return data
}

export async function updateMyAvatarApi(avatar_seed: string | null): Promise<ProfileUpdateResponse> {
  const { data } = await apiClient.patch<ProfileUpdateResponse>("/auth/me/avatar", {
    avatar_seed,
    clear_avatar: avatar_seed == null,
  })
  return data
}

/** Server revoke current session (best-effort before local clear). */
export async function logoutApi(): Promise<void> {
  await apiClient.post("/auth/logout")
}

