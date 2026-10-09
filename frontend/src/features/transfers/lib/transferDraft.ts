/**
 * transferDraft.ts — черновик массовой передачи (#325).
 *
 * Массовый режим передач держал два состояния: набранное в строках
 * (`bulkQuantities`) и набранное в шапках групп (`bulkGroupQuantities`), — а
 * раскладку группы по строкам и снятие нулевых строк при отправке делал прямо
 * в разметке страницы. Одно правило ввода жило в четырёх местах и могло
 * разойтись: поле шапки показало бы одно, а уехало другое.
 *
 * Здесь черновик — один модуль: набранное в строках и в шапках групп,
 * распределение группы по строкам (`planTransferQuantities`), сумма группы и
 * снятие нулевых строк при отправке. Режимов «+N»/целевого значения у передач
 * нет (решение грилла #325): количество строки — ровно её доступное
 * (`transferable_quantity`), пока оператор ничего не набрал.
 *
 * Ключ строки — `readyRowIdentity` (пара «задание × размер»): строки
 * виртуализированы, поэтому набранное привязано к идентификатору строки, а не
 * к её позиции в списке.
 */
import type { ReadyToTransferTask } from "@/shared/api/transfers";
import { readyRowIdentity, type ReadyTransferGroup } from "./groupReadyTransfers";
import { enteredTransferQuantity, planTransferQuantities } from "./runTransferBatch";

/** Черновик: набранное в строках и в шапках групп. */
export type TransferDraft = {
  /** Набранное в строках; строка без записи идёт своим `transferable`. */
  rowQuantities: Record<string, string>;
  /** Набранное в шапке группы — поле шапки показывает его как есть. */
  groupQuantities: Record<string, string>;
};

export const EMPTY_TRANSFER_DRAFT: TransferDraft = { rowQuantities: {}, groupQuantities: {} };

/** Набранное в строке, или `undefined`, если ввода нет. */
export function draftRowInput(draft: TransferDraft, row: ReadyToTransferTask): string | undefined {
  return draft.rowQuantities[readyRowIdentity(row)];
}

/** Количество строки: набранное, иначе — своё доступное. */
export function draftRowQuantity(draft: TransferDraft, row: ReadyToTransferTask): string {
  return enteredTransferQuantity(row, draft.rowQuantities);
}

/**
 * Черновик после правки строки. Правка снимает набранное в шапке группы: поле
 * шапки выводится из строк, и оставленный текст показывал бы не то, что уедет.
 */
export function withRowInput(
  draft: TransferDraft,
  groupKey: string | null,
  row: ReadyToTransferTask,
  value: string,
): TransferDraft {
  const rowQuantities = { ...draft.rowQuantities, [readyRowIdentity(row)]: value };
  if (!groupKey || !(groupKey in draft.groupQuantities)) {
    return { rowQuantities, groupQuantities: draft.groupQuantities };
  }
  const groupQuantities = { ...draft.groupQuantities };
  delete groupQuantities[groupKey];
  return { rowQuantities, groupQuantities };
}

/**
 * Черновик после правки шапки группы: набранное раскладывается по строкам тем
 * же правилом, что отправка (`planTransferQuantities`). Очистка снимает
 * раскладку — строки возвращаются к своему доступному.
 */
export function withGroupInput(
  draft: TransferDraft,
  group: ReadyTransferGroup,
  value: string,
): TransferDraft {
  const rowQuantities = { ...draft.rowQuantities };
  if (value.trim() === "") {
    for (const row of group.rows) delete rowQuantities[readyRowIdentity(row)];
  } else {
    const { quantities } = planTransferQuantities(group.rows, parseFloat(value) || 0);
    group.rows.forEach((row, index) => {
      rowQuantities[readyRowIdentity(row)] = quantities[index];
    });
  }
  return { rowQuantities, groupQuantities: { ...draft.groupQuantities, [group.key]: value } };
}

/** Значение поля шапки группы: набранное, иначе — сумма количеств её строк. */
export function draftGroupQuantity(draft: TransferDraft, group: ReadyTransferGroup): string {
  const typed = draft.groupQuantities[group.key];
  if (typed !== undefined) return typed;
  return String(
    group.rows.reduce((sum, row) => sum + (parseFloat(draftRowQuantity(draft, row)) || 0), 0),
  );
}

/**
 * Строки к отправке: нулевые (хвост раскладки группы) не отправляются вовсе —
 * правило то же, что в футере (`draftRowQuantity`).
 */
export function draftRowsToSend(
  draft: TransferDraft,
  tasks: ReadyToTransferTask[],
): ReadyToTransferTask[] {
  return tasks.filter((task) => (parseFloat(draftRowQuantity(draft, task)) || 0) > 0);
}
