import type { SortConfig } from "@/shared/hooks/useTableQueryEngine";
import { buildSortParam } from "@/shared/lib/sortQueryParam";
import { pickColumnApiValue, pickExactMatchColumnValue } from "@/shared/lib/columnFilterSearch";
import type { PlanSortField } from "./plan-labels";
import type { AllPlanPositionsParams } from "@/shared/api/productionPlans";

/**
 * Соответствие «колонка плана → поле сортировки all-positions».
 *
 * Ключ, которого здесь нет, сервер сортировать не умеет: `route` собирается
 * в Python (`resolve_position_route`, ADR про dynamic build) и не выводится
 * в SQL, `warnings` берётся из последнего PlanChangeItem позиции, а не из
 * агрегата, — оба значения нельзя честно выразить в ORDER BY. Подставлять
 * вместо них другое поле нельзя (пользователь увидит чужой порядок строк),
 * поэтому маппинг возвращает `undefined`, а колонка остаётся без иконки
 * сортировки (см. `SortableFilterHeader` prop `sortable`).
 *
 * Набор полей на backend: ALL_POSITIONS_SORT_FIELDS в
 * backend/app/api/routes/production_plans.py.
 */
const PLAN_SORT_FIELD_TO_API: Partial<Record<PlanSortField, string>> = {
  id: "id",
  rowNum: "source_row_number",
  sku: "source_sku",
  name: "source_name",
  qty: "quantity",
  dimensions: "dimensions",
  status: "status",
  validation: "validation_status",
  errors: "errors",
};

/** Поле сортировки для API или `undefined`, если сервер его не поддерживает. */
export function mapPlanSortFieldToApi(field: PlanSortField): string | undefined {
  return PLAN_SORT_FIELD_TO_API[field];
}

/**
 * Строка `?sort=...` по всем выбранным приоритетам, от старшего к младшему.
 * Колонки без серверной сортировки (route, warnings) в строку не попадают.
 * Если поддерживаемых полей нет, возвращается `undefined`: параметр не
 * уезжает вовсе и действует дефолт сервера.
 */
export function buildPlanSortParam(
  sortConfigs: SortConfig<PlanSortField>[],
): AllPlanPositionsParams["sort"] {
  return buildSortParam(sortConfigs, mapPlanSortFieldToApi);
}

export function buildPlanColumnApiParams(
  columnFilters: Partial<Record<PlanSortField, Set<string>>>,
  columnSearchQueries: Partial<Record<PlanSortField, string>>,
): Pick<
  AllPlanPositionsParams,
  "source_sku" | "source_name" | "has_route" | "has_errors" | "has_warnings" | "dimensions"
> {
  const params: Pick<
    AllPlanPositionsParams,
    "source_sku" | "source_name" | "has_route" | "has_errors" | "has_warnings" | "dimensions"
  > = {};

  const sourceSku = pickColumnApiValue(columnFilters, columnSearchQueries, "sku");
  if (sourceSku) params.source_sku = sourceSku;

  const sourceName = pickColumnApiValue(columnFilters, columnSearchQueries, "name");
  if (sourceName) params.source_name = sourceName;

  const routeValue = pickColumnApiValue(columnFilters, columnSearchQueries, "route");
  if (routeValue === "Не назначен") {
    params.has_route = "no";
  } else if (routeValue) {
    params.has_route = "yes";
  }

  const errorsValue = pickColumnApiValue(columnFilters, columnSearchQueries, "errors");
  if (errorsValue === "0") {
    params.has_errors = "no";
  } else if (errorsValue) {
    params.has_errors = "yes";
  }

  const warningsValue = pickColumnApiValue(columnFilters, columnSearchQueries, "warnings");
  if (warningsValue === "0") {
    params.has_warnings = "no";
  } else if (warningsValue) {
    params.has_warnings = "yes";
  }

  const dimensions = pickExactMatchColumnValue(columnFilters, "dimensions");
  if (dimensions) params.dimensions = dimensions;

  return params;
}