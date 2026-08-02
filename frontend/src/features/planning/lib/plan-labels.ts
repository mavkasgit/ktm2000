import { PlanPositionOut } from "@/shared/api/productionPlans"
import { errorLabels, statusLabels, validationLabels, warningLabels } from "@/shared/lib/generated-labels"

export { errorLabels, statusLabels, validationLabels, warningLabels }
export { errorLabels as routeErrorLabels } from "@/shared/lib/generated-labels"

export const planStatusLabels = statusLabels
export const planValidationLabels = validationLabels

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

export interface PlanFiltersState {
  status: "all" | "draft" | "valid" | "invalid"
  validation_status: "all" | "valid" | "invalid"
  has_route: "all" | "yes" | "no"
  has_errors: "all" | "yes" | "no"
  has_warnings: "all" | "yes" | "no"
  has_duplicates: "all" | "yes" | "no"
}

const STATUS_HISTORY_REASON_EXACT: Record<string, string> = {
  "Auto-released when fully covered by release batches":
    "Автозапуск при полном покрытии партиями выпуска",
}

const STATUS_TOKEN_IN_QUOTES_RE = /'([a-z_]+)'/gi

function translateEmbeddedStatusToken(status: string): string {
  return statusLabels[status] || planStatusLabels[status] || status
}

/** Переводит reason/message из истории смен статуса для UI. */
export function translateStatusHistoryReason(reason: string | null | undefined): string {
  if (!reason?.trim()) return "—"

  const trimmed = reason.trim()
  const exact = STATUS_HISTORY_REASON_EXACT[trimmed]
  if (exact) return exact

  return trimmed.replace(STATUS_TOKEN_IN_QUOTES_RE, (_match, status: string) => {
    const normalized = status.toLowerCase()
    return `'${translateEmbeddedStatusToken(normalized)}'`
  })
}
