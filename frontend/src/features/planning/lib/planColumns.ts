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
