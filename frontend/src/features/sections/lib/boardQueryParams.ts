import { pickColumnApiValue } from "@/shared/lib/columnFilterSearch";
import { exactMatchColumnParams } from "@/shared/lib/columnSpecs";
import { boardColumns } from "./boardColumns";
import { buildSortParam } from "@/shared/lib/sortQueryParam";
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

/**
 * Колонки доски, сортируемые сервером, и их поля в ORDER BY бэкенда
 * (`shopfloor/sections/{id}/board`).
 *
 * Числовые колонки (план, выдано, остаток и прочие количества) в таблице
 * отсутствуют: сервер отдаёт их из кэша задания, сортировать их в SQL нечем —
 * их сортирует клиент поверх ответа. Подставлять вместо них `sequence`
 * нельзя: оператор кликнул «План» и увидел перестановку по номеру задания.
 */
export const TASK_SORT_FIELD_TO_API = {
  sequence: "sequence",
  productSku: "product_sku",
  status: "status",
  dimensions: "dimensions",
} as const;

export type TaskServerSortApiField = (typeof TASK_SORT_FIELD_TO_API)[keyof typeof TASK_SORT_FIELD_TO_API];

/**
 * Поле колонки → поле, принимаемое API. `undefined` — сервер эту колонку
 * не сортирует, отправлять сортировку по ней нельзя.
 */
export function mapTaskSortFieldToApi(field: TaskSortField): TaskServerSortApiField | undefined {
  return (TASK_SORT_FIELD_TO_API as Partial<Record<TaskSortField, TaskServerSortApiField>>)[field];
}

export function isServerSortField(field: TaskSortField): boolean {
  return mapTaskSortFieldToApi(field) !== undefined;
}

export function buildBoardColumnApiParams(
  columnFilters: Partial<Record<TaskSortField, Set<string>>>,
  columnSearchQueries: Partial<Record<TaskSortField, string>>,
): Pick<SectionBoardQueryParams, "product_sku" | "dimensions"> {
  const productSku = pickColumnApiValue(columnFilters, columnSearchQueries, "productSku");
  // Колонки, объявившие точный фильтр, — из описания, а не перечислением.
  const exactMatch = exactMatchColumnParams(columnFilters, boardColumns);
  return {
    ...(productSku ? { product_sku: productSku } : {}),
    ...(exactMatch.dimensions ? { dimensions: exactMatch.dimensions } : {}),
  };
}

/**
 * Параметры доски, которые уходят на сервер. Сортировка собирается в одну
 * строку `sort` по всем выбранным приоритетам; колонки, которые сервер
 * сортировать не умеет (числовые количества, остаток), в строку не попадают —
 * их сортирует клиент поверх ответа (см. `sortedTasks` в SectionTasksBoard).
 * Если среди приоритетов нет ни одного серверного поля, `sort` не уходит
 * вовсе и действует дефолт сервера — подменять его чужим полем нельзя.
 */
export function buildBoardServerQueryParams(opts: {
  search?: string;
  columnFilters: Partial<Record<TaskSortField, Set<string>>>;
  columnSearchQueries: Partial<Record<TaskSortField, string>>;
  sortConfigs: SortConfig<TaskSortField>[];
}): Pick<SectionBoardQueryParams, "search" | "product_sku" | "dimensions" | "sort"> {
  const { search, columnFilters, columnSearchQueries, sortConfigs } = opts;
  const columnParams = buildBoardColumnApiParams(columnFilters, columnSearchQueries);

  return {
    search: search?.trim() || undefined,
    ...columnParams,
    sort: buildSortParam(sortConfigs, mapTaskSortFieldToApi),
  };
}