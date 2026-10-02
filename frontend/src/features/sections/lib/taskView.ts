/**
 * lib/taskView.ts — представление задания на доске участка.
 *
 * Одно решение о состоянии задания, одна раскладка на раскладки: строка
 * таблицы и карточка узкого экрана берут здесь и тон, и цвет точки статуса, и
 * подпись группы. Раньше эти решения жили в трёх местах и разошлись: панель
 * массовых операций (удалена в #283, ADR-0064) не считала полностью переданное
 * задание зелёным (#191).
 *
 * Модуль чистый: без JSX и без стилей. Классы раскладок — в
 * `components/TaskView.tsx`, там же собираются узлы полей.
 */

import type { SectionBoardTask } from "@/shared/api/shopfloor";
import {
  getReadyStatusLabel,
  isTaskFullyTransferred,
  getTaskViewCategory,
} from "./taskStatus";
import { QTY_EMPTY } from "@/shared/lib/quantityFormat";

/**
 * Тон задания: «в ожидании», «в работе», «взято в работу», «завершено»,
 * «обычное». Определяется один раз; строка и карточка только раскладывают его
 * в свои классы.
 */
export type TaskTone = "waiting" | "activeRunning" | "active" | "completed" | "plain";

export function getTaskTone(task: SectionBoardTask): TaskTone {
  const category = getTaskViewCategory(task);
  if (category === "waiting") return "waiting";
  if (category === "completed") return "completed";
  if (category === "active") {
    return ["in_progress", "in_work"].includes(task.status) ? "activeRunning" : "active";
  }
  return "plain";
}

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
    const rank = GROUP_TONE_PRIORITY.indexOf(getTaskTone(task));
    if (rank !== -1 && rank < best) best = rank;
  }
  return GROUP_TONE_PRIORITY[best];
}

/**
 * Цвет точки статуса. Полностью переданное задание считается завершённым
 * независимо от флага статуса — иначе доска и карточка показывали одно задание
 * разным цветом.
 */
export function getStatusDotClass(task: SectionBoardTask): string {
  const status = task.status;
  if (isTaskFullyTransferred(task)) return "bg-emerald-500";
  if (["in_progress", "in_work"].includes(status)) return "bg-amber-500 animate-pulse";
  if (["ready", "partially_completed", "partially"].includes(status)) {
    return status === "ready" && getReadyStatusLabel(task) === "Не передано"
      ? "bg-slate-400"
      : "bg-blue-500";
  }
  if (["completed", "done"].includes(status)) return "bg-emerald-500";
  if (status === "blocked") return "bg-red-500";
  if (["waiting_previous", "pending"].includes(status)) return "bg-yellow-400";
  return "bg-slate-300";
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
