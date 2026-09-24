import { PlanPositionOut } from "@/shared/api/productionPlans"
import type { BadgeProps } from "@/shared/ui/badge"
import { errorLabels, errorPhraseTranslations, statusLabels, warningLabels } from "@/shared/lib/generated-labels"

export { errorLabels, statusLabels, warningLabels }
export { errorLabels as routeErrorLabels } from "@/shared/lib/generated-labels"

export const planStatusLabels = statusLabels

export const statusVariant: Record<string, NonNullable<BadgeProps["variant"]>> = {
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
  const [base, ...rest] = String(code).split(":")
  const label = labels[base] ?? base
  return rest.length > 0 ? `${label}: ${rest.join(":")}` : label
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

export type PlanSortField = "id" | "rowNum" | "sku" | "name" | "qty" | "route" | "dimensions" | "status" | "validation" | "errors" | "warnings"

export interface PlanFiltersState {
  status: "all" | "draft" | "valid" | "invalid"
  validation_status: "all" | "valid" | "invalid"
  has_route: "all" | "yes" | "no"
  has_errors: "all" | "yes" | "no"
  has_warnings: "all" | "yes" | "no"
  has_duplicates: "all" | "yes" | "no"
}

const STATUS_HISTORY_REASON_EXACT: Record<string, string> =
  errorPhraseTranslations

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
