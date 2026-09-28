import type { ExecutionSortField } from "../components/execution-utils";
import type { SortConfig } from "@/shared/hooks/useTableQueryEngine";
import { buildSortParam } from "@/shared/lib/sortQueryParam";

/**
 * Поля сортировки, которые понимает бэкенд.
 *
 * Источник истины — `ROWS_SORT_FIELDS` в
 * `backend/app/services/production_planning_rows.py`: запрос с неизвестным
 * полем сортировки молча превращается в дефолтный порядок, поэтому таблица
 * не может отправлять поле, которого нет в этом списке.
 *
 * Поля `id`, `name`, `route` серверной сортировки не имеют: в списке бэкенда
 * нет ни `plan_position_id`, ни `source_name`, ни имени маршрута. Подставлять
 * вместо них чужие поля нельзя — порядок строк будет не тот, обещанный шапкой.
 */
export const EXECUTION_SORT_FIELD_TO_API = {
  row: "row_number",
  sku: "product_sku",
  status: "status",
  qty: "planned_qty",
  stage: "sequence",
  dimensions: "dimensions",
} as const;

export type ExecutionSortableField = keyof typeof EXECUTION_SORT_FIELD_TO_API;

export type ExecutionSortApiField =
  (typeof EXECUTION_SORT_FIELD_TO_API)[ExecutionSortableField];

const SORT_FIELD_TO_API: Partial<Record<ExecutionSortField, ExecutionSortApiField>> =
  EXECUTION_SORT_FIELD_TO_API;

/**
 * Поле колонки → поле, принимаемое API. `undefined` — сервер не умеет
 * сортировать по этой колонке, отправлять сортировку по ней нельзя.
 */
export function mapExecutionSortFieldToApi(
  field: ExecutionSortField,
): ExecutionSortApiField | undefined {
  return SORT_FIELD_TO_API[field];
}

/**
 * Строка `?sort=...` по всем выбранным приоритетам, от старшего к младшему.
 * Несортируемые сервером колонки (ID, наименование, маршрут) в строку не
 * попадают; если таких нет, строка пуста и действует дефолт сервера.
 */
export function buildExecutionSortParam(
  sortConfigs: SortConfig<ExecutionSortField>[],
): string | undefined {
  return buildSortParam(sortConfigs, mapExecutionSortFieldToApi);
}

