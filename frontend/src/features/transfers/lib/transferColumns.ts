/**
 * Описание колонок передач — единственное место, где объявляется, что это за
 * колонка, как она фильтруется, сортируется и какими параметрами уезжает в
 * запрос (#198, ADR-0038).
 *
 * Пока параметры собирались в `buildReadyColumnApiParams` и
 * `buildHistoryColumnApiParams`, а значение «—» отбрасывалось в шести местах
 * двумя способами, колонка называлась и в разметке шапки, и в сборке.
 */
import { formatDimensionsFilterValue, formatDimensionsLabel } from "@/shared/api/stock";
import type { ReadyToTransferTask } from "@/shared/api/transfers";
import type { ColumnSpec } from "@/shared/lib/columnSpecs";
import { fmtQty } from "@/shared/lib/quantityFormat";

import type { HistorySortField, ReadySortField } from "./transferSortParams";

export type ReadyColumn = ColumnSpec<ReadySortField> & {
  id: string;
  label: string;
  /** Все колонки готовых к передаче фильтруемые. */
  filterField: ReadySortField;
};

export type HistoryColumn = ColumnSpec<HistorySortField> & {
  id: string;
  label: string;
  /** Класс `<th>` сверх общего: выравнивание и ширина. */
  headerClassName?: string;
};

/** «—» — это пусто, а не значение: сервер такого не понимает. */
const dropDash = (value: string) => (value === "—" ? undefined : value);

/**
 * Значение ячейки «Готово к передаче» так, как его читает оператор: по нему
 * строится и список значений фильтра колонки, и лист печати. Пока функция
 * жила в странице, лист печати собирал бы свои значения — и напечатанное
 * расходилось бы с тем, что видно на экране.
 */
export function getReadyCellValue(task: ReadyToTransferTask, field: ReadySortField): string {
  switch (field) {
    case "positionId":
      return String(task.plan_position_id);
    case "sku":
      return task.product_sku ?? "—";
    case "dimensions":
      return formatDimensionsLabel(task.dimensions, task.dimensions_label);
    case "stage":
      return task.operation_name ?? "—";
    case "transferableQty":
      return fmtQty(task.transferable_quantity);
    case "next":
      return task.has_next_step
        ? `${task.next_operation_name ?? "—"} / ${task.next_section_name ?? "—"}`
        : "Финальный";
  }
}

/** Ячейка участка хранит операцию вместе с участком: «Пиление / Упаковка». */
const sectionNameOnly = (cellValue: string): string => cellValue.split(" / ")[0]?.trim() ?? cellValue;

/** Ячейка статуса — «Входящая / Принята», серверу нужен только код. */
const transferStatusCode = (label: string): string | undefined => {
  const part = label.split(" / ").pop()?.trim();
  switch (part) {
    case "Аннулирована":
      return "cancelled";
    case "Отправлена":
      return "sent";
    case "Частично принята":
      return "partially_accepted";
    case "Принята":
      return "accepted";
    default:
      return undefined;
  }
};

/**
 * «Пиление / Упаковка» — это операция и участок сразу, в одном значении.
 * Разделитель берётся первый: « / » встречается и внутри названия участка,
 * а разбор по всем вхождениям отбрасывал бы хвост названия. «—» — пустое
 * значение, сервер такого не понимает.
 */
const splitNext = (value: string): Record<string, string> => {
  if (value === "Финальный") return {};
  const separator = value.indexOf(" / ");
  const operation = (separator === -1 ? value : value.slice(0, separator)).trim();
  const section = separator === -1 ? undefined : value.slice(separator + 3).trim();
  const params: Record<string, string> = {};
  if (operation && operation !== "—") params.next_operation_name = operation;
  if (section && section !== "—") params.next_section_name = section;
  return params;
};

export const readyColumns: ReadyColumn[] = [
  {
    id: "positionId",
    label: "ID",
    filterField: "positionId",
    sortField: "positionId",
    apiParam: "plan_position_id",
    // Номер позиции — число, а не строка: нечисловой ввод в фильтр не уходит.
    mapValue: (value) => (Number.isFinite(Number(value)) ? value : undefined),
    valueLabel: (value) => `#${value}`,
  },
  {
    id: "sku",
    label: "Артикул",
    filterField: "sku",
    sortField: "sku",
    apiParam: "product_sku",
    mapValue: dropDash,
  },
  {
    id: "dimensions",
    label: "Размер",
    filterField: "dimensions",
    sortField: "dimensions",
    // Оператор выбирает габарит из списка, а не ищет подстроку в подписи.
    exactMatch: true,
    valueLabel: formatDimensionsFilterValue,
  },
  {
    id: "stage",
    label: "Этап",
    filterField: "stage",
    sortField: "stage",
    apiParam: "operation_name",
    mapValue: dropDash,
  },
  {
    id: "transferableQty",
    label: "К передаче",
    filterField: "transferableQty",
    sortField: "transferableQty",
    apiParam: "transferable_qty",
    valueLabel: (value) => `${value} шт.`,
  },
  { id: "next", label: "Следующий", filterField: "next", sortField: "next", toParams: splitNext },
];

/**
 * Журнал передач. Колонка «Размер» объявлена без фильтра и без сортировки:
 * `TransferHistoryListParams` такого параметра не знает, и
 * `listTransferHistory` его не сериализует. Добавить фильтр — значит сперва
 * расширить контракт бэкенда, а не выдумывать параметр на фронте.
 */
export const historyColumns: HistoryColumn[] = [
  { id: "positionId", label: "ID", headerClassName: "font-mono" },
  {
    id: "from",
    label: "Отправитель (Откуда)",
    filterField: "from",
    sortField: "from",
    apiParam: "from_section_name",
    mapValue: sectionNameOnly,
  },
  {
    id: "to",
    label: "Получатель (Куда)",
    filterField: "to",
    sortField: "to",
    apiParam: "to_section_name",
    mapValue: sectionNameOnly,
  },
  { id: "sku", label: "Артикул", filterField: "sku", sortField: "sku", apiParam: "product_sku" },
  { id: "dimensions", label: "Размер" },
  {
    id: "quantity",
    label: "Кол-во",
    headerClassName: "text-right",
    // Фильтра нет: `transfer_history_generic` такого параметра не принимает,
    // и `listTransferHistory` его не сериализует. Попапер выбора количества
    // не делал ничего. Сортировка по количеству серверу знакома, поэтому она
    // остаётся.
    sortField: "quantity",
  },
  {
    id: "status",
    label: "Статус",
    filterField: "status",
    sortField: "status",
    apiParam: "status",
    mapValue: transferStatusCode,
  },
  { id: "expansion", label: "", headerClassName: "w-[40px]" },
];
