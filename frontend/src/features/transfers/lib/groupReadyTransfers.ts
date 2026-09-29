import type { ReadyToTransferTask } from "@/shared/api/transfers";
import { formatDimensionsLabel } from "@/shared/api/stock";

/**
 * Единица передачи — пара «задание × размер», но оператору удобнее отправить одним
 * действием строки, неразличимые для передачи: тот же артикул, того же размера,
 * с того же участка и в тот же адрес. Такие строки собираются в одну (свёрнутую
 * по умолчанию) группу.
 *
 * Свёрнутая группа показывает СВОДНЫЕ значения (общий этап, сумма
 * `transferable_quantity`), поэтому порядок групп — порядок первого появления
 * строки — не выражает сортировку ни по одной из этих колонок. Поэтому
 * страница применяет группировку только когда сортировка не выбрана, а при
 * выбранной колонке рисует строки заданий как есть (см. `TransfersPage`).
 *
 * Участок и адресат обязательны в ключе. Страница грузит ready по ГХП, то есть
 * сразу по нескольким участкам; а ГП и П/ф — разные динамические маршруты
 * (`output_kind` в имени маршрута, см. `seeds/selection_rules.py`), поэтому по
 * `route_stage_id` они разошлись бы уже на первом участке. Ключ по участку и
 * адресату даёт то, что нужно производству: до анода ГП и П/ф идут в один адрес
 * и образуют одну строку, на аноде адресаты расходятся — строк становится две.
 */
export type ReadyTransferGroupCommon = {
  /** Подпись размера, общая для группы; `null` — строки группы не совпали (в UI «—»). */
  dimensionsLabel: string | null;
  operationName: string | null;
  nextOperationName: string | null;
  nextSectionName: string | null;
};

export type ReadyTransferGroup = {
  kind: "group";
  key: string;
  productSku: string | null;
  sectionId: number;
  nextSectionId: number | null;
  /** Строки группы в порядке прихода с бэка. */
  rows: ReadyToTransferTask[];
  /** Сумма `transferable_quantity` по строкам группы. */
  totalTransferable: number;
  /** Все строки группы — финальный выпуск («Отправить» вместо «Передать»). */
  allFinal: boolean;
  hasNextStep: boolean;
  common: ReadyTransferGroupCommon;
};

export type ReadyTransferSingle = {
  kind: "single";
  row: ReadyToTransferTask;
};

export type ReadyTransferRowItem = ReadyTransferGroup | ReadyTransferSingle;

/**
 * Подпись адресата передачи для колонки «Следующий» — одна строка по-русски.
 *
 * Код участка (`FINISHED_STOCK`) и номер этапа маршрута в таблице не печатаются:
 * оператору нужен адрес, а не идентификатор. Операция приоритетнее названия
 * участка, потому что в маршрутах она уже уточняет адрес («Хранение: Склад
 * готовой продукции»), но у складских этапов операций нет — там остаётся
 * название участка.
 */
export function nextStepLabel(operationName: string | null, sectionName: string | null): string {
  return operationName || sectionName || "—";
}

/** Строка в ready-списке = финальный выпуск, а не передача на следующий этап. */
export function isFinalReadyRow(task: ReadyToTransferTask): boolean {
  return task.is_final === true || !task.has_next_step;
}

/** Канонический вид размеров для ключа: ключи по алфавиту, `null` — отдельное состояние. */
export function dimensionsKey(dimensions: ReadyToTransferTask["dimensions"]): string {
  if (dimensions == null) return "null";
  const keys = Object.keys(dimensions).sort();
  if (keys.length === 0) return "null";
  return keys.map((key) => `${key}=${dimensions[key]}`).join(",");
}

/**
 * Идентичность строки ready-таблицы: единица передачи — пара «задание × размер».
 *
 * Один `task_id` у трансформирующей задачи (#91) даёт столько строк, сколько
 * выходов спецификации, поэтому `task_id` как ключ React не уникален. На этом
 * готовом ключе строились дубли `<tr>` — React переиспользовал узлы строк с
 * одинаковым ключом, и в DOM оказывалось больше строк, чем отдал сервер.
 *
 * Владелец выражения — здесь, рядом с `dimensionsKey`: его используют и
 * `data-row-key`, и React-ключ, и они не должны разойтись при правке одного.
 */
export function readyRowIdentity(task: ReadyToTransferTask): string {
  return `${task.task_id}:${dimensionsKey(task.dimensions)}`;
}

/** Ключ идентичности строки ready — см. комментарий к модулю. */
export function readyTransferGroupKey(task: ReadyToTransferTask): string {
  return [
    task.product_sku ?? "",
    task.section_id,
    dimensionsKey(task.dimensions),
    task.next_section_id ?? "final",
  ].join("|");
}

function sameValue<T>(rows: ReadyToTransferTask[], pick: (row: ReadyToTransferTask) => T): T | null {
  const [first] = rows;
  const value = pick(first);
  return rows.every((row) => pick(row) === value) ? value : null;
}

export function groupReadyTransfers(items: ReadyToTransferTask[]): ReadyTransferRowItem[] {
  const buckets = new Map<string, ReadyToTransferTask[]>();

  for (const task of items) {
    const key = readyTransferGroupKey(task);
    const bucket = buckets.get(key);
    if (bucket) {
      bucket.push(task);
    } else {
      buckets.set(key, [task]);
    }
  }

  const result: ReadyTransferRowItem[] = [];

  for (const [key, rows] of buckets) {
    if (rows.length < 2) {
      result.push({ kind: "single", row: rows[0] });
      continue;
    }

    let totalTransferable = 0;
    let allFinal = true;
    for (const row of rows) {
      const value = parseFloat(row.transferable_quantity);
      if (Number.isFinite(value)) totalTransferable += value;
      if (!isFinalReadyRow(row)) allFinal = false;
    }

    result.push({
      kind: "group",
      key,
      productSku: rows[0].product_sku,
      sectionId: rows[0].section_id,
      nextSectionId: rows[0].next_section_id,
      rows,
      totalTransferable,
      allFinal,
      hasNextStep: rows[0].has_next_step,
      common: {
        dimensionsLabel: sameValue(rows, (row) => formatDimensionsLabel(row.dimensions, row.dimensions_label)),
        operationName: sameValue(rows, (row) => row.operation_name),
        nextOperationName: sameValue(rows, (row) => row.next_operation_name),
        nextSectionName: sameValue(rows, (row) => row.next_section_name),
      },
    });
  }

  return result;
}
