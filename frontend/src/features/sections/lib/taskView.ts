/**
 * lib/taskView.ts — представление задания на доске участка.
 *
 * Одно решение о состоянии задания, одна раскладка на раскладки: строка
 * таблицы, карточка узкого экрана и панель массовых операций берут здесь и
 * тон, и цвет точки статуса, и подпись группы, и прогресс выходов. Раньше эти
 * решения жили в трёх местах и разошлись: панель массовых операций не считала
 * полностью переданное задание зелёным (#191).
 *
 * Модуль чистый: без JSX и без стилей. Классы раскладок — в
 * `components/TaskView.tsx`, там же собираются узлы полей.
 */

import type { SectionBoardTask } from "@/shared/api/shopfloor";
import { formatDimensionsLabel } from "@/shared/api/stock";
import {
  getReadyStatusLabel,
  isTaskCompletable,
  isTaskFullyTransferred,
  getTaskViewCategory,
} from "./taskStatus";
import { QTY_EMPTY, fmtQty } from "@/shared/lib/quantityFormat";

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
 * Цвет точки статуса. Полностью переданное задание считается завершённым
 * независимо от флага статуса — иначе доска и панель массовых операций
 * показывали одно задание разным цветом.
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

/**
 * Прогресс по выходам трансформирующего задания (ADR-0002) одной строкой.
 * `null` — прогресса нет, раскладка ничего не рисует.
 */
export function getTaskOutputsProgressText(task: SectionBoardTask): string | null {
  if (!task.transforms_dimensions || !task.outputs_progress?.length) return null;
  return task.outputs_progress
    .map((row) => `${formatDimensionsLabel(row.dimensions)}: ${fmtQty(row.produced_quantity)}/${fmtQty(row.quantity)}`)
    .join(" · ");
}

export type TaskGroupHeaderState = {
  /** Сворачивание: в массовом режиме группа выбирается целиком, а не прячется. */
  isCollapsed: boolean;
  canCollapse: boolean;
  collapseTitle: string;
  allSelected: boolean;
  hasCompletable: boolean;
  completeTitle: string;
};

/** Состояние шапки группы — одно для строки таблицы и для карточки группы. */
export function getTaskGroupHeaderState(
  group: { tasks: SectionBoardTask[] },
  options: { isCollapsed: boolean; isBulkMode: boolean; allSelected: boolean },
): TaskGroupHeaderState {
  const hasCompletable = group.tasks.some(isTaskCompletable);
  return {
    isCollapsed: options.isCollapsed,
    canCollapse: !options.isBulkMode,
    collapseTitle: options.isCollapsed ? "Раскрыть" : "Скрыть",
    allSelected: options.allSelected,
    hasCompletable,
    completeTitle: hasCompletable
      ? "Открыть панель завершения группы"
      : "Все задания в группе завершены",
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
 * Первая операция участка — та, что стоит в колонке «Операция».
 *
 * Берётся первая операция этапа, а не «эффективная» (`operation_name`): туда
 * попадает и ручной выбор операции, и она может оказаться упаковочной — тогда
 * цвет позиции в «Операции» утонул бы в списке. Упаковочная операция первой в
 * «Операции» не показывается вовсе: её несёт колонка «Упаковка».
 */
export function taskPrimaryOperation(task: SectionBoardTask): string {
  const codes = task.operation_codes ?? [];
  const names = task.operation_names ?? [];
  const firstCode = codes[0];
  if (!firstCode || !firstCode.startsWith(PACKAGING_OPERATION_PREFIX)) {
    return names[0]?.trim() || task.operation_name?.trim() || "";
  }
  return "";
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
