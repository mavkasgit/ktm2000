import type { SortConfig } from "@/shared/hooks/useTableQueryEngine";
import { buildSortParam } from "@/shared/lib/sortQueryParam";

/** Колонки панели «Наличие на участках» с сортируемой шапкой. */
export type BalanceSortField = "sku" | "quantity" | "operations" | "quality" | "location";

/** Колонки ящика истории транзакций с сортируемой шапкой. */
export type TransactionSortField =
  | "date"
  | "reason"
  | "from"
  | "to"
  | "quantity"
  | "quality"
  | "comment";

/** Колонки таблицы превью импорта остатков с сортируемой шапкой. */
export type RemainderPreviewSortField =
  | "row"
  | "sku"
  | "quantity"
  | "length"
  | "operations"
  | "quality"
  | "section"
  | "errors";

/**
 * Поле колонки остатков → поле `?sort=` (ORDER BY бэкенда, BALANCE_SORT_FIELDS
 * в backend/app/stock/api.py). Все колонки панели сервер сортировать умеет,
 * поэтому подменять одну колонку полем другой здесь нечего.
 */
const BALANCE_SORT_FIELD_TO_API: Record<BalanceSortField, string> = {
  sku: "sku",
  quantity: "quantity",
  operations: "operations",
  quality: "quality",
  location: "location",
};

/**
 * Поле колонки транзакции → поле `?sort=` (TX_SORT_FIELDS там же). Дата в
 * колонке это `created_at` в ORDER BY, участки — имена `from_section`/`to_section`,
 * поэтому имена колонок короткие, а поля API длиннее.
 */
const TRANSACTION_SORT_FIELD_TO_API: Record<TransactionSortField, string> = {
  date: "created_at",
  reason: "reason",
  from: "from_location",
  to: "to_location",
  quantity: "quantity",
  quality: "quality_state",
  comment: "comment",
};

/**
 * Поля превью импорта остатков уходят под теми же именами, что и колонки
 * (REMAINDER_PREVIEW_SORT_FIELDS в backend/app/stock/import_service.py).
 */
const REMAINDER_PREVIEW_SORT_FIELD_TO_API: Record<RemainderPreviewSortField, string> = {
  row: "row",
  sku: "sku",
  quantity: "quantity",
  length: "length",
  operations: "operations",
  quality: "quality",
  section: "section",
  errors: "errors",
};

export function mapBalanceSortFieldToApi(field: BalanceSortField): string | undefined {
  return BALANCE_SORT_FIELD_TO_API[field];
}

export function mapTransactionSortFieldToApi(field: TransactionSortField): string | undefined {
  return TRANSACTION_SORT_FIELD_TO_API[field];
}

export function mapRemainderPreviewSortFieldToApi(field: RemainderPreviewSortField): string | undefined {
  return REMAINDER_PREVIEW_SORT_FIELD_TO_API[field];
}

/** Порядок остатков, пока оператор ничего не выбрал (совпадает с дефолтом бэкенда). */
export const DEFAULT_BALANCE_SORT = "sku:asc";

/** Порядок истории транзакций по умолчанию: свежие движения сверху. */
export const DEFAULT_TRANSACTION_SORT = "created_at:desc";

/** Порядок превью импорта по умолчанию: строки файла сверху, как в Excel. */
export const DEFAULT_REMAINDER_PREVIEW_SORT = "row:asc";

/**
 * Строка `?sort=` по всем выбранным приоритетам, от старшего к младшему.
 * Пустой набор сортировок даёт дефолт эндпоинта: сортировки нет — действует
 * то, что сервер и так вернул бы.
 */
export function buildBalanceSortParam(sortConfigs: SortConfig<BalanceSortField>[]): string {
  return buildSortParam(sortConfigs, mapBalanceSortFieldToApi) ?? DEFAULT_BALANCE_SORT;
}

export function buildTransactionSortParam(
  sortConfigs: SortConfig<TransactionSortField>[],
): string {
  return buildSortParam(sortConfigs, mapTransactionSortFieldToApi) ?? DEFAULT_TRANSACTION_SORT;
}

export function buildRemainderPreviewSortParam(
  sortConfigs: SortConfig<RemainderPreviewSortField>[],
): string {
  return (
    buildSortParam(sortConfigs, mapRemainderPreviewSortFieldToApi) ??
    DEFAULT_REMAINDER_PREVIEW_SORT
  );
}
