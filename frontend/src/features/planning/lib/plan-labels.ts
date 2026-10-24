import { PlanPositionOut } from "@/shared/api/productionPlans"
import type { BadgeProps } from "@/shared/ui/badge"
import type { FiltersPanelOption } from "@/shared/ui"
import { errorLabels, statusLabels, validationLabels, warningLabels } from "@/shared/lib/generated-labels"

import { positionWarnings } from "@/shared/lib/planWarnings"

export { errorLabels, statusLabels, warningLabels }
export { actionLabels } from "@/shared/lib/generated-labels"
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
    // Риск для утверждения дают и предупреждения — берутся с позиции (#328).
    positionWarnings(pos).length > 0 ||
    (pos.errors && pos.errors.length > 0)
  return hasRouteProblems || Boolean(duplicateConflict && duplicateConflict.conflictIds.length > 0)
}

export type PlanSortField = "id" | "rowNum" | "sku" | "name" | "qty" | "route" | "dimensions" | "status" | "validation" | "errors" | "warnings"

export interface PlanFiltersState {
  status: "all" | "draft" | "valid" | "invalid"
  /** Состояния валидации позиции; «перекрыта» — форс-аппрув с причиной (#212). */
  validation_status: "all" | keyof typeof validationLabels
  has_route: "all" | "yes" | "no"
  has_errors: "all" | "yes" | "no"
  has_warnings: "all" | "yes" | "no"
  has_duplicates: "all" | "yes" | "no"
}

/**
 * Варианты панельного фильтра по валидации. Список и подписи берутся из канона:
 * новое состояние валидации попадает в фильтр само, дописывать его здесь не надо.
 */
export const validationFilterOptions: FiltersPanelOption[] = [
  { value: "all", label: "Все" },
  ...Object.keys(validationLabels).map((value) => ({
    value,
    label: validationLabels[value],
  })),
]
