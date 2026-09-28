import type { SortConfig } from "@/shared/hooks/useTableQueryEngine";
import { buildSortParam } from "@/shared/lib/sortQueryParam";

/** Колонки таблицы «Готово к передаче» с сортируемой шапкой. */
export type ReadySortField =
  | "positionId"
  | "sku"
  | "dimensions"
  | "stage"
  | "transferableQty"
  | "next";

/** Колонки журнала передач с сортируемой шапкой. */
export type HistorySortField = "from" | "to" | "sku" | "quantity" | "status";

/**
 * Колонка «Готово к передаче» → поле `?sort=`
 * (READY_SORT_FIELDS в backend/app/transfers/queries.py). Все шесть колонок
 * сервер сортировать умеет.
 */
const READY_SORT_FIELD_TO_API: Record<ReadySortField, string> = {
  positionId: "plan_position_id",
  sku: "product_sku",
  dimensions: "dimensions",
  stage: "operation_name",
  transferableQty: "transferable_qty",
  next: "next_section_name",
};

/**
 * Колонка журнала → поле `?sort=`. Имена полей журнала — псевдонимы контракта
 * API (`from`, `to`, `sku`, `quantity`), их резолвит бэкенд; переименовывать
 * под имена колонок нельзя.
 */
const HISTORY_SORT_FIELD_TO_API: Record<HistorySortField, string> = {
  from: "from",
  to: "to",
  sku: "sku",
  quantity: "quantity",
  status: "status",
};

export function mapReadySortFieldToApi(field: ReadySortField): string | undefined {
  return READY_SORT_FIELD_TO_API[field];
}

export function mapHistorySortFieldToApi(field: HistorySortField): string | undefined {
  return HISTORY_SORT_FIELD_TO_API[field];
}

/** Порядок «Готово к передаче» по умолчанию: этап маршрута, потом номер задания. */
export const DEFAULT_READY_SORT = "sequence:asc";

/** Порядок журнала передач по умолчанию: свежие передачи сверху. */
export const DEFAULT_HISTORY_SORT = "created_at:desc";

/**
 * Строка `?sort=` по всем выбранным приоритетам, от старшего к младшему.
 * Пустой набор даёт дефолт эндпоинта: сортировки нет — порядок сервера.
 */
export function buildReadySortParam(sortConfigs: SortConfig<ReadySortField>[]): string {
  return buildSortParam(sortConfigs, mapReadySortFieldToApi) ?? DEFAULT_READY_SORT;
}

export function buildHistorySortParam(sortConfigs: SortConfig<HistorySortField>[]): string {
  return buildSortParam(sortConfigs, mapHistorySortFieldToApi) ?? DEFAULT_HISTORY_SORT;
}
