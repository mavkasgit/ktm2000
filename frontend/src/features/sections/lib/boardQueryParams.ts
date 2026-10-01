import { buildColumnApiParams } from "@/shared/lib/columnSpecs";
import { boardColumns } from "./boardColumns";
import { buildSortParam } from "@/shared/lib/sortQueryParam";
import type { SortConfig } from "@/shared/hooks/useTableQueryEngine";
import type {
  SectionBoardColumnValuesParams,
  SectionBoardQueryParams,
} from "@/shared/api/shopfloor";

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

/**
 * Параметры фильтров колонок для запроса доски. Собираются общим сборщиком
 * по описанию колонок: перечисления полей здесь нет, поэтому новая
 * серверная колонка не требует правки этого файла, а колонка, помеченная
 * `clientOnly`, в запрос не попадает сама.
 */
export function buildBoardColumnApiParams(
  columnFilters: Partial<Record<TaskSortField, Set<string>>>,
  columnSearchQueries: Partial<Record<TaskSortField, string>>,
): Pick<SectionBoardQueryParams, "product_sku" | "dimensions"> {
  const params = buildColumnApiParams(columnFilters, columnSearchQueries, boardColumns);
  return {
    ...(params.product_sku !== undefined ? { product_sku: params.product_sku } : {}),
    ...(params.dimensions !== undefined ? { dimensions: params.dimensions } : {}),
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

/**
 * Колонки доски, значения которых берутся из серверного справочника (#211).
 *
 * Здесь только фильтруемые сервером колонки, у которых домен значения
 * совпадает с доменом фильтра. «Размер» в список не входит: колонка
 * показывает `input_dimensions` трансформирующих задач, а фильтр доски
 * сравнивает `WorkTask.dimensions` — значение из справочника не сузило бы
 * выборку. Заводить справочник для клиентских колонок незачем: их значения
 * экран фильтрует сам по загруженным строкам (ADR-0044).
 */
export const BOARD_SERVER_VALUE_FIELDS: readonly TaskSortField[] = ["productSku"];

/** Сколько значений справочника запрашивать: срез сверху, признак — `truncated`. */
export const BOARD_COLUMN_VALUES_LIMIT = 200;

/**
 * Параметры запроса справочника значений колонки: те же фильтры, что у доски
 * (окно дат, поиск, фильтры колонок), но без её сортировки и пагинации —
 * справочник не зависит от страницы. Фильтр самой колонки уходит на сервер и
 * отбрасывается там: список не должен схлопываться к выбранному значению.
 */
export function buildBoardColumnValuesParams(opts: {
  column: string;
  filters: Pick<
    SectionBoardQueryParams,
    "date_from" | "date_to" | "status" | "search" | "product_sku" | "dimensions"
  >;
  limit?: number;
}): SectionBoardColumnValuesParams {
  const { date_from, date_to, status, search, product_sku, dimensions } = opts.filters;
  return {
    column: opts.column,
    date_from,
    date_to,
    status,
    search,
    product_sku,
    dimensions,
    limit: opts.limit ?? BOARD_COLUMN_VALUES_LIMIT,
  };
}