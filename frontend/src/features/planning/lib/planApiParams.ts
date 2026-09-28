import type { SortConfig } from "@/shared/hooks/useTableQueryEngine";
import { buildSortParam } from "@/shared/lib/sortQueryParam";
import { buildColumnApiParams } from "@/shared/lib/columnSpecs";
import type { PlanSortField } from "./plan-labels";
import { planColumns } from "./planColumns";
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

/**
 * Параметры запроса, которые дают отфильтрованные колонки плана. Имена полей
 * серверные и не совпадают с именами колонок — «Артикул» едет как
 * `source_sku`, поэтому тип назван здесь, а не выведен из функции.
 */
export type PlanColumnApiParams = Pick<
  AllPlanPositionsParams,
  "source_sku" | "source_name" | "has_route" | "has_errors" | "has_warnings" | "dimensions"
>;

/** Значения панели фильтров плана: «all» — фильтр не выбран. */
export type PlanPanelFilters = {
  status: string;
  validationStatus: string;
  hasRoute: string;
  hasErrors: string;
  hasWarnings: string;
};

export function buildPlanColumnApiParams(
  columnFilters: Partial<Record<PlanSortField, Set<string>>>,
  columnSearchQueries: Partial<Record<PlanSortField, string>>,
): PlanColumnApiParams {
  return buildColumnApiParams(columnFilters, columnSearchQueries, planColumns);
}

/**
 * Параметры запроса всех позиций плана.
 *
 * Собирались прямо в компоненте, перечислением полей. Из-за этого фильтр
 * «Размер» терялся: сборщик колонок его отдавал, а страница перечисляла поля
 * запроса руками и `dimensions` среди них не было — колонка была видна и не
 * фильтровала ничего.
 *
 * Панельный фильтр имеет приоритет над фильтром колонки по тому же полю:
 * оператор, выбравший «с ошибками» в панели, ждёт именно его.
 */
export function buildPlanPositionsQuery(
  columnApiParams: PlanColumnApiParams,
  options: {
    limit: number;
    offset: number;
    search: string;
    sort?: string;
    /** Значения панели: «all» означает «не выбран». */
    panel: PlanPanelFilters;
  },
): AllPlanPositionsParams {
  const { panel } = options;
  const chosen = (selected: string, fromColumn: string | undefined) =>
    selected !== "all" ? selected : fromColumn;

  return {
    limit: options.limit,
    offset: options.offset,
    search: options.search.trim() || undefined,
    sort: options.sort,
    status: chosen(panel.status, undefined),
    validation_status: chosen(panel.validationStatus, undefined),
    has_route: chosen(panel.hasRoute, columnApiParams.has_route),
    has_errors: chosen(panel.hasErrors, columnApiParams.has_errors),
    has_warnings: chosen(panel.hasWarnings, columnApiParams.has_warnings),
    source_sku: columnApiParams.source_sku,
    source_name: columnApiParams.source_name,
    dimensions: columnApiParams.dimensions,
  };
}
