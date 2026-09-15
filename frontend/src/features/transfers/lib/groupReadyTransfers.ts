import type { ReadyToTransferTask } from "@/shared/api/transfers";

/**
 * Единица передачи — пара «задание × размер», но оператору удобнее отправить одним
 * действием строки, неразличимые для передачи: тот же артикул, того же размера,
 * с того же участка и в тот же адрес. Такие строки собираются в одну (свёрнутую
 * по умолчанию) группу.
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
  sequence: number | null;
  nextOperationName: string | null;
  nextSectionCode: string | null;
  nextStepSequence: number | null;
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
        dimensionsLabel: sameValue(rows, (row) => row.dimensions_label),
        operationName: sameValue(rows, (row) => row.operation_name),
        sequence: sameValue(rows, (row) => row.sequence),
        nextOperationName: sameValue(rows, (row) => row.next_operation_name),
        nextSectionCode: sameValue(rows, (row) => row.next_section_code),
        nextStepSequence: sameValue(rows, (row) => row.next_step_sequence),
      },
    });
  }

  return result;
}
