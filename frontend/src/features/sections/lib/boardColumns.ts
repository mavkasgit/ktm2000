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
import type { SectionBoardTask } from "@/shared/api/shopfloor";
import type { ColumnSpec } from "@/shared/lib/columnSpecs";
import { formatDimensionsFilterValue } from "@/shared/api/stock";
import { fmtQty } from "@/shared/lib/quantityFormat";
import { getTaskRowState } from "./taskStatus";
import { taskGroupingDimensions } from "./groupTasksByProfile";

import type { TaskSortField } from "./boardQueryParams";

export type BoardColumn = ColumnSpec<TaskSortField, TaskSortField, SectionBoardTask> & {
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
  /**
   * Колонка применима только к участку с упаковочными операциями
   * (`Section.has_packaging`). Признак живёт здесь, рядом с колонкой, а не
   * проверкой в разметке: шапка, число колонок и тело строки обязаны прятать
   * её в один момент, иначе шапка и ячейки разъезжаются.
   */
  requiresPackaging?: boolean;
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
    cellValue: (task) => task.product_sku,
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
    // Значение колонки — сериализованный габарит: он же уезжает параметром
    // запроса и он же лежит в списке попапера. Подпись (`formatDimensionsLabel`)
    // — только для показа, у колонки с ячейкой `CutLayoutCell`.
    cellValue: (task) => JSON.stringify(taskGroupingDimensions(task) ?? null),
    sortValues: (a, b) => formatDimensionsFilterValue(a).localeCompare(formatDimensionsFilterValue(b), "ru"),
  },
  { id: "operation", label: "Операция", className: left },
  // Упаковка — вторая операция участка. Показывается видом и количеством:
  // колонка клиентская, сервер фильтров по ней не знает.
  // Есть не везде: у пилы упаковочных операций нет вовсе (см. `has_packaging`
  // в ответе справочника участков), и пустая колонка на каждой строке читается
  // как «данные не пришли», а не как «здесь этого не бывает».
  { id: "packaging", label: "Упаковка", className: left, requiresPackaging: true },
  // Количества и статус доска фильтрует сама, по уже пришедшим строкам:
  // сервер фильтров по ним не знает, и отправка подписанного значения
  // («Годные», «12 шт.») сузила бы выборку до пустой.
  { id: "plannedQty", label: "План", className: left, filterField: "plannedQty", sortField: "plannedQty", clientOnly: true, cellValue: (task) => fmtQty(task.planned_quantity) },
  { id: "issuedQty", label: "Выдано", className: left, filterField: "issuedQty", sortField: "issuedQty", clientOnly: true, cellValue: (task) => fmtQty(task.cache.issued_quantity) },
  { id: "completedQty", label: "Годные", className: left, filterField: "completedQty", sortField: "completedQty", clientOnly: true, cellValue: (task) => fmtQty(task.cache.completed_quantity) },
  { id: "rejectedQty", label: "Брак", className: left, filterField: "rejectedQty", sortField: "rejectedQty", clientOnly: true, cellValue: (task) => fmtQty(task.cache.rejected_quantity) },
  { id: "transferredQty", label: "Передано", className: left, filterField: "transferredQty", sortField: "transferredQty", clientOnly: true, cellValue: (task) => fmtQty(task.cache.transferred_quantity) },
  { id: "remainingQty", label: "Остаток", className: left, filterField: "remainingQty", sortField: "remainingQty", clientOnly: true, cellValue: (task) => fmtQty(task.cache.remaining_quantity) },
  {
    id: "status",
    label: "Статус",
    className: left,
    filterField: "status",
    sortField: "status",
    clientOnly: true,
    // Значение — та же подпись, что в пилюле строки (`getTaskRowState`), поэтому
    // список попапера и фильтр читают одно решение, а не собирают своё.
    cellValue: (task) => getTaskRowState(task).label,
  },
  {
    id: "actions",
    label: "Действия",
    // Нижняя граница ширины под кнопку и видимую причину недоступности рядом
    // с ней (#193). Текст причины не переносится и не обрезается, а при
    // auto-layout таблица всё равно расширится, если места не хватит.
    className: `${left} w-64`,
  },
];

/**
 * Колонки, применимые к участку: «Упаковка» — только там, где у участка есть
 * упаковочные операции (`Section.has_packaging`).
 *
 * Флага нет (`undefined` — старый кэш, ошибка справочника): не скрываем
 * ничего. Ошибка справочника не должна прятать данные, а на анодировании в
 * этой колонке лежит тип упаковки, а не украшение шапки.
 */
export function visibleBoardColumns(hasPackaging: boolean | undefined): BoardColumn[] {
  return boardColumns.filter((column) => !column.requiresPackaging || hasPackaging !== false);
}
