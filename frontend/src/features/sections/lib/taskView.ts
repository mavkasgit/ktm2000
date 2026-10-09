/**
 * lib/taskView.ts — представление задания на доске участка.
 *
 * Раньше этот модуль держал и решение о состоянии задания, и раскладку: строка,
 * карточка и подпись группы брали отсюда тон и цвет точки. С #324 решение
 * переехало в `getTaskRowState` (`lib/taskStatus.ts`) — одно место на категорию,
 * тон, подпись и оба класса; здесь остаётся раскладка (тон группы, операции,
 * упаковка). История расхождения — панель массовых операций (удалена в #283,
 * ADR-0064) не считала полностью переданное задание зелёным (#191).
 *
 * Модуль чистый: без JSX и без стилей. Классы раскладок — в
 * `components/TaskView.tsx`, там же собираются узлы полей.
 */

import type { SectionBoardTask } from "@/shared/api/shopfloor";
import { getTaskRowState, type TaskTone } from "./taskStatus";
import { QTY_EMPTY } from "@/shared/lib/quantityFormat";

/**
 * Тон группы — один на весь блок: раскрытая группа показывает задания одного
 * артикула, разрезанные по операциям, и общий фон читается как «одно задание»,
 * а построчные тона превращали её в набор независимых строк.
 *
 * Порядок — «что требует внимания сейчас»: в работе → взято → ожидание →
 * завершено → обычное. Группа с одной работающей строкой подсвечивается как
 * работающая: оператор ищет глазами работу, а не большинство.
 */
const GROUP_TONE_PRIORITY: TaskTone[] = ["activeRunning", "active", "waiting", "completed", "plain"];

export function getGroupTone(tasks: SectionBoardTask[]): TaskTone {
  let best = GROUP_TONE_PRIORITY.length - 1;
  for (const task of tasks) {
    const rank = GROUP_TONE_PRIORITY.indexOf(getTaskRowState(task).tone);
    if (rank !== -1 && rank < best) best = rank;
  }
  return GROUP_TONE_PRIORITY[best];
}

export type TaskGroupHeaderState = {
  /** Сворачивание: в массовом режиме группа выбирается целиком, а не прячется. */
  isCollapsed: boolean;
  canCollapse: boolean;
  collapseTitle: string;
  allSelected: boolean;
};

/**
 * Состояние шапки группы — одно для строки таблицы и для карточки группы.
 * Причина недоступности завершения здесь больше не считается: кнопки
 * «Завершить группу» нет, а причина подтверждения живёт в футере и читается
 * по черновику (`bulkDraft`).
 */
export function getTaskGroupHeaderState(
  group: { tasks: SectionBoardTask[] },
  options: { isCollapsed: boolean; isBulkMode: boolean; allSelected: boolean },
): TaskGroupHeaderState {
  return {
    isCollapsed: options.isCollapsed,
    canCollapse: !options.isBulkMode,
    collapseTitle: options.isCollapsed ? "Раскрыть" : "Скрыть",
    allSelected: options.allSelected,
  };
}

/**
 * Префикс кодов упаковочных операций участка: `PACK`, `PACK_STRETCH`,
 * `PACK_SPUNBOND` (группа «Упаковка» в `SectionOperation`).
 */
const PACKAGING_OPERATION_PREFIX = "PACK";

/**
 * Упаковка задания — операция упаковки участка («Стрейч», «Спанбонд»,
 * «Упаковка») из операций его этапа. Описание упаковки из Excel-импорта в
 * план не выводится.
 */
export function taskPackaging(task: SectionBoardTask): string | null {
  const codes = task.operation_codes ?? [];
  const names = task.operation_names ?? [];
  const labels: string[] = [];

  for (const [index, code] of codes.entries()) {
    if (!code || !code.startsWith(PACKAGING_OPERATION_PREFIX)) continue;
    const name = names[index]?.trim();
    if (name && !labels.includes(name)) labels.push(name);
  }

  return labels.length > 0 ? labels.join(" + ") : null;
}

/**
 * Операции участка строки — список для колонки «Операция».
 *
 * Все операции этапа по порядку, а не только первая: на анодировании это цвет,
 * на прессе — вид обработки. Упаковочные операции в список не входят: их несёт
 * колонка «Упаковка» (ADR-0058, #210), поэтому строка с одной упаковкой даёт
 * пустой список — раскладка показывает прочерк. Если операций этапа нет вовсе,
 * берётся «эффективная» (`operation_name`).
 */
export function taskOperations(task: SectionBoardTask): string[] {
  const codes = task.operation_codes ?? [];
  const names = task.operation_names ?? [];
  const labels: string[] = [];

  for (const [index, code] of codes.entries()) {
    if (code && code.startsWith(PACKAGING_OPERATION_PREFIX)) continue;
    const name = names[index]?.trim();
    if (name && !labels.includes(name)) labels.push(name);
  }

  if (labels.length > 0) return labels;
  if (codes.length > 0) return [];
  const fallback = task.operation_name?.trim();
  return fallback ? [fallback] : [];
}

/**
 * Разбивка упаковки строки: вид упаковки → количество заданий этого вида.
 *
 * Строка доски объединяет позиции одного артикула и первой операции, поэтому
 * упаковка в ней может быть разной: «Спанбонд 180 · Стрейч 120». Количество —
 * план задания: речь о том, сколько материала пойдёт этим видом.
 */
export function packagingBreakdown(
  tasks: SectionBoardTask[],
): { label: string; qty: number }[] {
  const byLabel = new Map<string, number>();
  for (const task of tasks) {
    const label = taskPackaging(task);
    if (!label) continue;
    const planned = Number(task.planned_quantity);
    byLabel.set(label, (byLabel.get(label) ?? 0) + (Number.isFinite(planned) ? planned : 0));
  }
  const items = Array.from(byLabel, ([label, qty]) => ({ label, qty }));
  items.sort((a, b) => b.qty - a.qty || a.label.localeCompare(b.label, "ru"));
  return items;
}

/**
 * Подпись упаковки: нет видов — прочерк, один — только название, несколько —
 * название с количеством через « · ». Единственная реализация на доску и на
 * печатный лист.
 */
export function packagingLabel(
  items: { label: string; qty: number }[],
  formatQty: (value: number) => string,
): string {
  if (items.length === 0) return QTY_EMPTY;
  if (items.length === 1) return items[0].label;
  return items.map((item) => `${item.label} ${formatQty(item.qty)}`).join(" · ");
}

/** Подпись разбивки упаковки по заданиям строки. */
export function packagingBreakdownLabel(
  tasks: SectionBoardTask[],
  formatQty: (value: number) => string,
): string {
  return packagingLabel(packagingBreakdown(tasks), formatQty);
}
