import type { UserRole } from "@/features/auth/api"

export const ROLE_LABELS: Record<UserRole, string> = {
  admin: "Администратор",
  planner: "Планировщик",
  section_manager: "Начальник участка",
  operator: "Оператор",
  viewer: "Наблюдатель",
  transporter: "Транспортировщик",
}
