import { pickColumnApiValue, pickExactMatchColumnValue } from "@/shared/lib/columnFilterSearch";
import type { SortConfig } from "@/shared/hooks/useTableQueryEngine";
import type { SectionBoardQueryParams } from "@/shared/api/shopfloor";

export type TaskSortField =
  | "sequence"
  | "productSku"
  | "dimensions"
  | "plannedQty"
  | "issuedQty"
  | "completedQty"
  | "transferredQty"
  | "rejectedQty"
  | "remainingQty"
  | "status";

const SERVER_SORT_FIELDS = new Set<TaskSortField>([
  "sequence",
  "productSku",
  "status",
  "dimensions",
]);

export function mapTaskSortFieldToApi(field: TaskSortField): string | undefined {
  switch (field) {
    case "sequence":
      return "sequence";
    case "productSku":
      return "product_sku";
    case "status":
      return "status";
    case "dimensions":
      return "dimensions";
    default:
      return undefined;
  }
}

export function isServerSortField(field: TaskSortField): boolean {
  return SERVER_SORT_FIELDS.has(field);
}

export function buildBoardColumnApiParams(
  columnFilters: Partial<Record<TaskSortField, Set<string>>>,
  columnSearchQueries: Partial<Record<TaskSortField, string>>,
): Pick<SectionBoardQueryParams, "product_sku" | "dimensions"> {
  const productSku = pickColumnApiValue(columnFilters, columnSearchQueries, "productSku");
  const dimensions = pickExactMatchColumnValue(columnFilters, "dimensions");
  return {
    ...(productSku ? { product_sku: productSku } : {}),
    ...(dimensions ? { dimensions } : {}),
  };
}

export function buildBoardServerQueryParams(opts: {
  search?: string;
  columnFilters: Partial<Record<TaskSortField, Set<string>>>;
  columnSearchQueries: Partial<Record<TaskSortField, string>>;
  sortConfigs: SortConfig<TaskSortField>[];
}): Pick<SectionBoardQueryParams, "search" | "product_sku" | "dimensions" | "sort_by" | "sort_order"> {
  const { search, columnFilters, columnSearchQueries, sortConfigs } = opts;
  const columnParams = buildBoardColumnApiParams(columnFilters, columnSearchQueries);
  const activeSort = sortConfigs[0];
  const apiSortField = activeSort ? mapTaskSortFieldToApi(activeSort.field) : undefined;

  return {
    search: search?.trim() || undefined,
    ...columnParams,
    sort_by: apiSortField ?? (activeSort ? "sequence" : undefined),
    sort_order: activeSort?.order ?? "asc",
  };
}