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
  tab_number?: string | null
}

export interface UpdateUserInput {
  username?: string
  full_name?: string
  section_id?: number | null
  section_ids?: number[]
  is_active?: boolean
  tab_number?: string | null
}

export type ListUsersParams = {
  limit?: number
  offset?: number
  search?: string
  sort_by?: string
  sort_order?: "asc" | "desc"
  role?: string
  is_active?: boolean
  full_name?: string
  email?: string
  section?: string
}

export type UsersListResponse = {
  users: User[]
  total: number
  limit: number
  offset: number
}


/** Получить список пользователей с пагинацией и фильтрами */
export async function listUsers(params: ListUsersParams = {}): Promise<UsersListResponse> {
  const { data } = await apiClient.get<UsersListResponse>("/users", { params })
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

// ─── Employees (HRMS sync) ──────────────────────────────────────────

export interface Employee {
  id: number
  hrms_id: number
  name: string
  tab_number: string | null
  position: string | null
  department: string | null
}

export type ListEmployeesParams = {
  limit?: number
  offset?: number
  search?: string
  sort_by?: string
  sort_order?: "asc" | "desc"
  department?: string
}

export type EmployeeListResponse = {
  employees: Employee[]
  total: number
  limit: number
  offset: number
  synced_at: string | null
}

export type SyncDiffEntry = {
  id: number
  name: string
  tab_number: string | null
  position: string | null
  department: string | null
}

export type SyncChange = {
  before: SyncDiffEntry
  after: SyncDiffEntry
  fields: string[]
}

export type SyncDiff = {
  added: SyncDiffEntry[]
  removed: SyncDiffEntry[]
  changed: SyncChange[]
  unchanged_count: number
}

export type SyncPreviewResponse = {
  employees: SyncDiffEntry[]
  synced_at: string
  diff: SyncDiff
}

/** Получить список сотрудников из кеша */
export async function listEmployees(params: ListEmployeesParams = {}): Promise<EmployeeListResponse> {
  const { data } = await apiClient.get<EmployeeListResponse>("/employees", { params })
  return data
}

/** Синхронизировать сотрудников из HRMS */
export async function syncEmployees(): Promise<EmployeeListResponse> {
  const { data } = await apiClient.post<EmployeeListResponse>("/employees/sync")
  return data
}

/** Предпросмотр синхронизации (diff без записи) */
export async function previewEmployeesSync(): Promise<SyncPreviewResponse> {
  const { data } = await apiClient.post<SyncPreviewResponse>("/employees/sync/preview")
  return data
}
