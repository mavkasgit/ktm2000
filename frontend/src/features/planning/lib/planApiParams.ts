import type { AllPlanPositionsParams } from "@/shared/api/productionPlans";
import { pickColumnApiValue, pickExactMatchColumnValue } from "@/shared/lib/columnFilterSearch";
import type { PlanSortField } from "./plan-labels";

export function mapPlanSortFieldToApi(field: PlanSortField): string {
  switch (field) {
    case "rowNum":
      return "source_row_number";
    case "sku":
      return "source_sku";
    case "qty":
      return "quantity";
    case "dimensions":
      return "dimensions";
    case "status":
      return "status";
    case "validation":
      return "validation_status";
    default:
      return "source_row_number";
  }
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