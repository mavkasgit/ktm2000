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
  hrms_employee_id?: number | null
}

export interface UpdateUserInput {
  username?: string
  full_name?: string
  role?: UserRole
  section_id?: number | null
  section_ids?: number[]
  is_active?: boolean
  tab_number?: string | null
  hrms_employee_id?: number | null
}

export interface HrmsEmployee {
  id: number
  name: string
  tab_number: string | null
  position?: string
  department?: string
  is_linked?: boolean
}

export type HrmsEmployeesCacheResponse = {
  employees: HrmsEmployee[]
  synced_at: string | null
}

export type ListHrmsEmployeesParams = {
  limit?: number
  offset?: number
  search?: string
  sort_by?: string
  sort_order?: "asc" | "desc"
  department?: string
  linked?: boolean
}

export type HrmsEmployeesListResponse = {
  employees: HrmsEmployee[]
  total: number
  limit: number
  offset: number
  synced_at: string | null
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
  linked_hrms_ids: number[]
}

/** Получить кешированный список сотрудников HRMS из БД (пагинация) */
export async function listHrmsEmployees(
  params: ListHrmsEmployeesParams = {},
): Promise<HrmsEmployeesListResponse> {
  const { data } = await apiClient.get<HrmsEmployeesListResponse>("/users/employees", { params })
  return data
}

/** Получить весь кеш HRMS для диалогов/селектов (пагинация, max 500 на запрос). */
export async function getCachedHrmsEmployees(): Promise<HrmsEmployeesCacheResponse> {
  const pageSize = 500
  const all: HrmsEmployee[] = []
  let offset = 0
  let total = Infinity
  let synced_at: string | null = null

  while (offset < total) {
    const page = await listHrmsEmployees({ limit: pageSize, offset })
    all.push(...page.employees)
    total = page.total
    synced_at = page.synced_at
    offset += page.employees.length
    if (page.employees.length === 0) break
  }

  return {
    employees: all,
    synced_at,
  }
}

/** Синхронизировать кеш сотрудников HRMS из внешнего сервиса */
export async function syncHrmsEmployees(): Promise<HrmsEmployeesCacheResponse> {
  const { data } = await apiClient.post<HrmsEmployeesCacheResponse>("/users/employees/sync")
  return data
}

export type HrmsSyncField = "name" | "tab_number" | "position" | "department"

export type HrmsSyncDiffEntry = {
  id: number
  name: string
  tab_number: string | null
  position: string | null
  department: string | null
  is_linked: boolean
}

export type HrmsSyncChange = {
  before: HrmsSyncDiffEntry
  after: HrmsSyncDiffEntry
  fields: HrmsSyncField[]
}

export type HrmsSyncDiff = {
  added: HrmsSyncDiffEntry[]
  removed: HrmsSyncDiffEntry[]
  changed: HrmsSyncChange[]
  unchanged_count: number
}

export type HrmsSyncPreviewResponse = {
  employees: HrmsSyncDiffEntry[]
  synced_at: string
  diff: HrmsSyncDiff
}

/** Предпросмотр синхронизации — показывает diff без записи в БД */
export async function previewHrmsSync(): Promise<HrmsSyncPreviewResponse> {
  const { data } = await apiClient.post<HrmsSyncPreviewResponse>("/users/employees/sync/preview")
  return data
}

export type HrmsIntegrationSettings = {
  base_url: string | null
  api_token: string
  employees_url: string | null
  updated_at: string | null
}

export type HrmsConnectionTestResult = {
  request_url: string
  employee_count: number
}

/** Получить настройки подключения к HRMS */
export async function getHrmsSettings(): Promise<HrmsIntegrationSettings> {
  const { data } = await apiClient.get<HrmsIntegrationSettings>("/users/hrms-settings")
  return data
}

/** Сохранить настройки подключения к HRMS */
export async function saveHrmsSettings(payload: {
  base_url?: string | null
  api_token?: string | null
}): Promise<HrmsIntegrationSettings> {
  const { data } = await apiClient.put<HrmsIntegrationSettings>("/users/hrms-settings", payload)
  return data
}

/** Проверить подключение к HRMS (сохраняет адрес при успехе) */
export async function testHrmsConnection(payload: {
  base_url?: string | null
  api_token?: string | null
}): Promise<HrmsConnectionTestResult> {
  const { data } = await apiClient.post<HrmsConnectionTestResult>("/users/hrms-settings/test", payload)
  return data
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
