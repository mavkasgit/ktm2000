import { apiClient } from "@/shared/api/client"
import type { User, UserRole } from "@/features/auth/api"

export interface CreateUserInput {
  username: string
  email: string
  password?: string // Опционально, если бэкенд требует, но при создании пользователя пароль обязателен
  full_name: string
  role: UserRole
  section_id: number | null
  section_ids?: number[]
}

export interface UpdateUserInput {
  username?: string
  full_name?: string
  role?: UserRole
  section_id?: number | null
  section_ids?: number[]
  is_active?: boolean
}

/** Получить список всех пользователей */
export async function listUsers(): Promise<User[]> {
  const { data } = await apiClient.get<User[]>("/users")
  return data
}

/** Создать нового пользователя */
export async function createUser(payload: CreateUserInput): Promise<User> {
  const { data } = await apiClient.post<User>("/users", payload)
  return data
}

/** Обновить данные пользователя */
export async function updateUser(userId: number, payload: UpdateUserInput): Promise<User> {
  const { data } = await apiClient.patch<User>(`/users/${userId}`, payload)
  return data
}

/** Сбросить пароль пользователя */
export async function resetPassword(userId: number, newPassword: string): Promise<void> {
  await apiClient.post(`/users/${userId}/reset-password`, { new_password: newPassword })
}
