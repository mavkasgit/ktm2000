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
  hrms_employee_id?: number | null
  hrms_access_level?: string
  active_login_token?: ActiveToken | null
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

/** Параметры для генерации OTP кода */
export interface OTPGenerateInput {
  user_id: number
  session_duration_seconds: number | null
  code_lifetime_seconds?: number
}

/** Ответ на генерацию OTP кода */
export interface OTPGenerateResponse {
  token: string
  expires_at: string
}

/** Вход по OTP коду */
export async function loginWithOTPApi(token: string): Promise<TokenResponse> {
  const { data } = await apiClient.post<TokenResponse>("/auth/otp/login", { token })
  return data
}

/** Генерация OTP кода для пользователя */
export async function generateOTPApi(input: OTPGenerateInput): Promise<OTPGenerateResponse> {
  const { data } = await apiClient.post<OTPGenerateResponse>("/auth/otp/generate", input)
  return data
}

export interface OTPVerifyProfileResponse {
  username: string
  full_name: string
  is_password_set: boolean
}

export async function verifyOTPProfileApi(token: string): Promise<OTPVerifyProfileResponse> {
  const { data } = await apiClient.get<OTPVerifyProfileResponse>("/auth/otp/verify-profile", {
    params: { token },
  })
  return data
}

export async function setupPasswordWithOTPApi(token: string, password: string): Promise<TokenResponse> {
  const { data } = await apiClient.post<TokenResponse>("/auth/otp/setup-password", {
    token,
    password,
  })
  return data
}

