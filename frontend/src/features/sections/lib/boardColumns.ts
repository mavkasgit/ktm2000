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
  {
    id: "productSku",
    label: "Артикул",
    className: left,
    filterField: "productSku",
    sortField: "productSku",
    // Поле доски `productSku`, а параметр запроса — `product_sku`: имя
    // перекодировки объявлено здесь, а не в сборщике параметров.
    apiParam: "product_sku",
  },
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
  // Количества и статус доска фильтрует сама, по уже пришедшим строкам:
  // сервер фильтров по ним не знает, и отправка подписанного значения
  // («Годные», «12 шт.») сузила бы выборку до пустой.
  { id: "plannedQty", label: "План", className: left, filterField: "plannedQty", sortField: "plannedQty", clientOnly: true },
  { id: "issuedQty", label: "Выдано", className: left, filterField: "issuedQty", sortField: "issuedQty", clientOnly: true },
  { id: "completedQty", label: "Годные", className: left, filterField: "completedQty", sortField: "completedQty", clientOnly: true },
  { id: "rejectedQty", label: "Брак", className: left, filterField: "rejectedQty", sortField: "rejectedQty", clientOnly: true },
  { id: "transferredQty", label: "Передано", className: left, filterField: "transferredQty", sortField: "transferredQty", clientOnly: true },
  { id: "remainingQty", label: "Остаток", className: left, filterField: "remainingQty", sortField: "remainingQty", clientOnly: true },
  {
    id: "status",
    label: "Статус",
    className: left,
    filterField: "status",
    sortField: "status",
    clientOnly: true,
    // Значения статуса уже подписаны при сборе: `uniqueValues.status`
    // строится через `getStatusLabel`, поэтому переподписывать их нечего.
  },
  { id: "actions", label: "Действия", className: left },
];
