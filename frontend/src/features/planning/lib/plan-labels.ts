import { PlanPositionOut } from "@/shared/api/productionPlans"

export const statusLabels: Record<string, string> = {
  parsed: "Распознан",
  failed: "Ошибка",
  applied: "Применён",
  cancelled: "Отменён",
  draft: "Черновик",
  valid: "Валиден",
  invalid: "Ошибка",
  approved: "Утверждён",
  released: "Запущен",
}

export const statusVariant: Record<string, string> = {
  parsed: "secondary",
  failed: "destructive",
  applied: "default",
  cancelled: "destructive",
  draft: "secondary",
  valid: "default",
  invalid: "destructive",
  approved: "default",
  released: "default",
}

export const routeErrorLabels: Record<string, string> = {
  route_signature_incomplete: "Сигнатура маршрута неполная",
  route_not_found: "Маршрут не найден",
  no_route_candidate: "Нет маршрута под правила выбора",
  route_rule_conflict: "Конфликт правил выбора маршрута",
  route_contains_excluded_step: "Маршрут содержит исключённый участок",
  selection_rules: "Маршрут выбран правилами",
  active_route_not_found: "Активный маршрут не найден",
  active_route_has_no_steps: "Маршрут без этапов",
  route_sequence_invalid: "Неверная последовательность маршрута",
  route_contains_inactive_section: "Маршрут содержит неактивный участок",
  route_not_matching_import_signature: "Маршрут не совпадает с импортом",
  route_missing_required_step: "Отсутствует обязательный этап",
  route_missing_pack_additional_operation: "Отсутствует доп. упаковочная операция",
  route_primary_operation_mismatch: "Основная операция маршрута не совпадает",
  manual_route_not_found: "Ручной маршрут не найден",
  manual_route_inactive: "Ручной маршрут неактивен",
  auto_fallback: "Маршрут скорректирован автоматически — проверьте",
}

export const errorLabels: Record<string, string> = {
  product_not_found: "Изделие не найдено",
  product_inactive: "Изделие неактивно",
  active_techcard_not_found: "Нет активной техкарты",
  active_techcard_has_no_lines: "Техкарта пустая",
  active_route_not_found: "Нет активного маршрута",
  active_route_has_no_steps: "Маршрут без этапов",
  route_sequence_invalid: "Неверная последовательность маршрута",
  route_contains_inactive_section: "Неактивный участок в маршруте",
  duplicate_sku_due_date: "Дубликат строки Excel: такая же строка уже есть",
  route_primary_operation_mismatch: "Основная операция маршрута не совпадает",
  route_not_matching_import_signature: "Маршрут не совпадает с ожидаемым",
  route_missing_required_step: "Отсутствует обязательный этап в маршруте",
  route_missing_pack_additional_operation: "Отсутствует доп. упаковочная операция",
  quantity_must_be_positive: "Количество должно быть > 0",
  route_signature_incomplete: "Сигнатура маршрута неполная",
  route_not_found: "Маршрут не найден",
  no_route_candidate: "Нет маршрута под правила выбора",
  route_rule_conflict: "Конфликт правил выбора маршрута",
  route_contains_excluded_step: "Маршрут содержит исключённый участок",
  selection_rules: "Маршрут выбран правилами",
}

export const warningLabels: Record<string, string> = {
  paired_profile_product_unmapped: "Парный профиль не сопоставлен",
  techcard_pair_not_resolved: "Не выбран парный профиль техкарты",
  product_name_missing: "Отсутствует наименование",
  period_not_detected: "не определен",
  route_auto_fallback: "Маршрут скорректирован автоматически — проверьте корректность",
}

export function translateLabel(code: string, labels: Record<string, string>): string {
  const [base] = String(code).split(":")
  return labels[base] ?? code
}

export function formatRouteAssignedAt(value: string | null | undefined): string {
  if (!value) return "дата неизвестна"
  const dt = new Date(value)
  if (Number.isNaN(dt.getTime())) return "дата неизвестна"
  return dt.toLocaleString("ru-RU", {
    day: "2-digit",
    month: "2-digit",
    year: "numeric",
    hour: "2-digit",
    minute: "2-digit",
  })
}

export function routeMetaLabel(pos: PlanPositionOut): string {
  const assignedAt = formatRouteAssignedAt(pos.route_assigned_at)
  if (pos.route_source === "dynamic_build") {
    return `динамический • ${assignedAt}`
  }
  if (pos.route_origin === "manual_confirmed" || pos.route_source === "manual") {
    return `вручную • ${assignedAt}`
  }
  if (pos.route_origin === "auto" || pos.route_source === "auto") {
    const quality = pos.route_match_quality === "exact" ? "полное" : "скорректирован"
    return `автомаппинг (${quality}) • ${assignedAt}`
  }
  if (pos.route_origin === "legacy" || pos.route_source === "legacy") {
    return "legacy • дата неизвестна"
  }
  return ""
}

export type DuplicateConflict = {
  fingerprint: string
  conflictIds: number[]
}

export function isRiskyForApprove(pos: PlanPositionOut, duplicateConflict?: DuplicateConflict): boolean {
  const hasRouteProblems =
    pos.route_match_quality === "corrected" ||
    pos.route_origin === "legacy" ||
    pos.route_error !== null ||
    (pos.route_match_reason !== null &&
      pos.route_match_reason !== "selection_rules" &&
      pos.route_match_reason !== "wildcard_rule") ||
    (pos.warnings && pos.warnings.length > 0) ||
    (pos.errors && pos.errors.length > 0)
  return hasRouteProblems || Boolean(duplicateConflict && duplicateConflict.conflictIds.length > 0)
}

export type PlanSortField = "id" | "rowNum" | "sku" | "name" | "qty" | "route" | "status" | "validation" | "errors" | "warnings"

export const planStatusLabels: Record<string, string> = {
  draft: "Черновик",
  valid: "Валиден",
  invalid: "Ошибка",
  approved: "Утверждён",
  released: "Запущен",
}

export const planValidationLabels: Record<string, string> = {
  valid: "Пройдена",
  invalid: "Ошибка",
  pending: "Ожидает",
}

export interface PlanFiltersState {
  status: "all" | "draft" | "valid" | "invalid"
  validation_status: "all" | "valid" | "invalid"
  has_route: "all" | "yes" | "no"
  has_errors: "all" | "yes" | "no"
  has_warnings: "all" | "yes" | "no"
  has_duplicates: "all" | "yes" | "no"
}
