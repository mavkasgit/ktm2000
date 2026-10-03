/**
 * Описание колонок таблицы «В реальной работе» — тот же контракт, что у
 * таблицы остатков (ADR-0037, ADR-0038): колонка объявляет своё поле один
 * раз, а шапка и тело собираются оба из этого описания. Пока блок «в работе»
 * печатал `<th>` и `<td>` руками, его порядок колонок жил отдельно от
 * остальных таблиц и разъезжался с ними при любой правке.
 *
 * Числовые колонки объявлены сортируемыми без фильтра: попапер собрался бы
 * из всех количеств строк, и выбор «159» сужал бы таблицу сильнее, чем
 * помогал. Фильтр остаётся у той колонки, по которой оператор ищет, — у
 * операции.
 *
 * Таблица целиком клиентская: `getProductWipStats` знает только артикул, и
 * выбор в колонке не уезжает в запрос — поэтому у неё проставлен
 * `clientOnly`.
 */
import type { ProductWipTask } from "@/shared/api/productionPlans";
import { fmtQty } from "@/shared/lib/quantityFormat";
import type { ColumnSpec } from "@/shared/lib/columnSpecs";

/** Поля фильтра и сортировки блока «в работе». */
export type WipStatsTaskField =
  | "operation"
  | "dimensions"
  | "tasks"
  | "plan"
  | "issued"
  | "completed";

export type WipStatsTaskColumn = ColumnSpec<WipStatsTaskField> & {
  id: string;
  label: string;
  /** Класс `<th>` сверх общего: `p-0` у колонки с поповером и ширина. */
  headerClassName?: string;
};

/** Попапер фильтра рисует отступы сам, поэтому у фильтруемой колонки их нет. */
const filtered = "p-0";

/**
 * Порядок колонок совпадает с порядком `<td>` в `InWorkTaskRow`: операция,
 * размер, задачи, план, выдано, завершено.
 */
export const wipStatsTaskColumns: WipStatsTaskColumn[] = [
  {
    id: "operation",
    label: "Операция (участок)",
    filterField: "operation",
    sortField: "operation",
    // Ширина ограничена: блок «в работе» стоит в половине окна, и шесть
    // колонок обязаны поместиться в неё — иначе контейнер режет их по
    // `overflow-x-hidden` молча. Остаток (~80px на колонку) снимают с
    // числовых: под четыре цифры хватает 70px.
    headerClassName: `${filtered} min-w-[150px] max-w-[220px]`,
    clientOnly: true,
  },
  // Служебная колонка: «Размер» выводится из габаритов строки, фильтровать
  // его нечем (значения в поповере пришлось бы собирать из подписи размера),
  // и в запрос колонка не уезжает.
  { id: "dimensions", label: "Размер", headerClassName: "px-2 w-[80px]" },
  { id: "tasks", label: "Задач", sortField: "tasks", headerClassName: "w-[70px] text-center" },
  { id: "plan", label: "План", sortField: "plan", headerClassName: "w-[70px] text-right" },
  { id: "issued", label: "Выдано", sortField: "issued", headerClassName: "w-[70px] text-right" },
  { id: "completed", label: "Завершено", sortField: "completed", headerClassName: "w-[80px] text-right" },
];

/**
 * Значение ячейки, по которому работает клиентский фильтр. Числа отдаются
 * тем же форматтером, что печатает ячейка: иначе попапер предлагал бы
 * оператору значение, которого в строке нет.
 */
export function wipStatsTaskCellValue(row: ProductWipTask, field: WipStatsTaskField): string {
  switch (field) {
    case "operation":
      return row.operation_name;
    case "dimensions":
      return row.dimensions_label;
    case "tasks":
      return fmtQty(row.active_tasks_count);
    case "plan":
      return fmtQty(row.planned_qty);
    case "issued":
      return fmtQty(row.issued_qty);
    case "completed":
      return fmtQty(row.completed_qty);
  }
}

/**
 * Значение для сортировки. Количества остаются числами: сравнение строк дало
 * бы порядок «10» раньше «4».
 */
export function wipStatsTaskSortValue(
  row: ProductWipTask,
  field: WipStatsTaskField,
): string | number {
  switch (field) {
    case "operation":
      return row.operation_name;
    case "dimensions":
      return row.dimensions_label;
    case "tasks":
      return row.active_tasks_count;
    case "plan":
      return row.planned_qty;
    case "issued":
      return row.issued_qty;
    case "completed":
      return row.completed_qty;
  }
}