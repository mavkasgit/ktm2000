/**
 * Описание колонок плана позиций — единственное место, где объявляется, что
 * это за колонка, как она фильтруется, сортируется и каким параметром уезжает
 * в запрос (#198, ADR-0038).
 *
 * Пока семантика жила в разметке шапки и в `buildPlanColumnApiParams`, а между
 * ними — ручной вызов по имени поля «Размер», — выбор габарита доходил до
 * сборщика параметров и там терялся: страница перечисляла поля запроса руками
 * и `dimensions` среди них не было. Фильтр был виден и не работал.
 */
import { formatDimensionsFilterValue } from "@/shared/api/stock";
import type { ColumnSpec } from "@/shared/lib/columnSpecs";

import type { PlanSortField } from "./plan-labels";

/**
 * Все колонки плана фильтруемые, в том числе клиентские: `filterField`
 * обязателен, чтобы шапка не «забывала» колонку при перечислении.
 */
export type PlanColumn = ColumnSpec<PlanSortField> & {
  id: string;
  label: string;
  filterField: PlanSortField;
};

/** «Не назначен» и пустое значение — разные вещи, и «—» сервер не понимает. */
const toYesNo = (empty: string) => (value: string) =>
  value === "" ? undefined : value === empty ? "no" : "yes";

export const planColumns: PlanColumn[] = [
  { id: "id", label: "Id", filterField: "id", sortField: "id", clientOnly: true },
  { id: "rowNum", label: "Строка", filterField: "rowNum", sortField: "rowNum", clientOnly: true },
  { id: "sku", label: "Артикул", filterField: "sku", sortField: "sku", apiParam: "source_sku" },
  { id: "qty", label: "Кол-во", filterField: "qty", sortField: "qty", clientOnly: true },
  {
    id: "dimensions",
    label: "Размер",
    filterField: "dimensions",
    sortField: "dimensions",
    // Оператор выбирает габарит из списка, а не ищет подстроку в подписи.
    exactMatch: true,
    valueLabel: formatDimensionsFilterValue,
  },
  { id: "name", label: "Наименование", filterField: "name", sortField: "name", apiParam: "source_name" },
  {
    id: "route",
    label: "Маршрут",
    filterField: "route",
    apiParam: "has_route",
    mapValue: toYesNo("Не назначен"),
    // Маршрут собирается в Python и не выводится в SQL: подставлять вместо
    // него другое поле молча нельзя, поэтому иконки сортировки нет.
    //
    // Фильтр у этой колонки двойной. Сервер понимает только «назначен или
    // нет» (`has_route`), а конкретный маршрут он не фильтрует: значение
    // «Упаковка» превратилось бы в `has_route=yes` и выбрало бы все строки с
    // любым маршрутом. Поэтому конкретный маршрут страница сужает у себя,
    // а в запрос уходит только «назначен/не назначен». Проверка «уходит ли
    // этот фильтр на клиент» живёт здесь, `isRouteFilterClientSide`, а не в
    // странице: колонка одна, и её семантика не должна расходиться по двум
    // файлам.
  },
  {
    id: "errors",
    label: "Ошибки",
    filterField: "errors",
    sortField: "errors",
    apiParam: "has_errors",
    mapValue: toYesNo("0"),
  },
  {
    id: "warnings",
    label: "Предупр.",
    filterField: "warnings",
    apiParam: "has_warnings",
    mapValue: toYesNo("0"),
    // Предупреждения берутся из последнего PlanChangeItem позиции, а не из
    // агрегата, и в ORDER BY не выражаются.
  },
];

/** Подпись колонки для счётчика активных фильтров берётся отсюда же. */
export const planColumnLabels: Record<string, string> = Object.fromEntries(
  planColumns.map((column) => [column.filterField, column.label]),
);

/**
 * Колонки плана, которые страница сужает у себя: сервер фильтрует их не
 * умеет. Берётся из описания, а не перечисляется в странице — иначе
 * переименование колонки ломало бы фильтрацию молча.
 */
export const PLAN_CLIENT_FILTER_FIELDS: PlanSortField[] = planColumns
  .filter((column) => column.clientOnly)
  .map((column) => column.filterField);

/**
 * Уходит ли фильтр колонки «Маршрут» на клиент.
 *
 * Истина для конкретного маршрута: сервер такого параметра не знает и вместо
 * фильтра вернул бы все строки с назначенным маршрутом. Ложь для
 * «Не назначен» — это `has_route=no`, и такой фильтр серверный.
 */
export function isRouteFilterClientSide(
  columnFilters: Partial<Record<PlanSortField, Set<string>>>,
  columnSearchQueries: Partial<Record<PlanSortField, string>>,
): boolean {
  const value =
    columnFilters.route?.size === 1
      ? [...columnFilters.route][0]
      : columnSearchQueries.route?.trim() || undefined;
  return Boolean(value && value !== "Не назначен");
}
