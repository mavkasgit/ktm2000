/**
 * Описание колонок доски участка — единственное место, где объявляется, что
 * это за колонка, как она фильтруется, сортируется и как подписываются её
 * значения (#197, ADR-0037).
 *
 * Пока шапка собиралась тринадцатью блоками `<th>` руками, колонка «Размер»
 * была единственной, у которой фильтр и подпись значений отличались от
 * остальных, и это отличие жило в разметке. Описание переносит его в данные:
 * добавление колонки или смена её семантики больше не трогает шапку.
 */
import type { ColumnSpec } from "@/shared/lib/columnSpecs";
import { formatDimensionsFilterValue } from "@/shared/api/stock";

import type { TaskSortField } from "./boardQueryParams";

export type BoardColumn = ColumnSpec<TaskSortField> & {
  id: string;
  label: string;
  /** Класс `<th>`: выравнивание и служебные колонки. */
  className?: string;
  /**
   * Поле сортировки, объявленное в описании. Отличается от `sortField`
   * базового типа тем, что здесь это то, что видно оператору, а совместимость
   * с сервером решается отдельно через `isServerSortField`.
   */
  sortField?: TaskSortField;
};

const left = "text-left";

export const boardColumns: BoardColumn[] = [
  { id: "statusDot", label: "Статус", className: "w-12 text-center" },
  { id: "productSku", label: "Артикул", className: left, filterField: "productSku", sortField: "productSku" },
  {
    id: "dimensions",
    label: "Размер",
    className: left,
    filterField: "dimensions",
    sortField: "dimensions",
    // «Размер» — выбор габарита из списка, а не поиск подстроки в подписи.
    exactMatch: true,
    valueLabel: formatDimensionsFilterValue,
  },
  { id: "operation", label: "Операция", className: left },
  { id: "plannedQty", label: "План", className: left, filterField: "plannedQty", sortField: "plannedQty" },
  { id: "issuedQty", label: "Выдано", className: left, filterField: "issuedQty", sortField: "issuedQty" },
  { id: "completedQty", label: "Годные", className: left, filterField: "completedQty", sortField: "completedQty" },
  { id: "rejectedQty", label: "Брак", className: left, filterField: "rejectedQty", sortField: "rejectedQty" },
  { id: "transferredQty", label: "Передано", className: left, filterField: "transferredQty", sortField: "transferredQty" },
  { id: "remainingQty", label: "Остаток", className: left, filterField: "remainingQty", sortField: "remainingQty" },
  {
    id: "status",
    label: "Статус",
    className: left,
    filterField: "status",
    sortField: "status",
    // Значения статуса уже подписаны при сборе: `uniqueValues.status`
    // строится через `getStatusLabel`, поэтому переподписывать их нечего.
  },
  { id: "actions", label: "Действия", className: left },
];
