import { apiClient } from "@/shared/api/client"

export type SessionDto = {
  id: string
  device_label: string | null
  ip_address: string | null
  user_agent: string | null
  login_method: string
  created_at: string
  last_seen_at: string
  is_current: boolean
}

export function formatLoginMethod(method: string | null | undefined): string {
  switch (method) {
    case "password":
      return "Пароль"
    case "invite":
      return "Инвайт"
    case "otp":
      return "Одноразовый код"
    case "oidc":
      return "Единый вход"
    default:
      return method || "—"
  }
}

export async function fetchSessions(): Promise<SessionDto[]> {
  const { data } = await apiClient.get<SessionDto[]>("/auth/sessions")
  return data
}

export async function revokeSession(id: string): Promise<void> {
  await apiClient.delete(`/auth/sessions/${id}`)
}

export async function revokeOtherSessions(): Promise<void> {
  await apiClient.delete("/auth/sessions/others")
}
