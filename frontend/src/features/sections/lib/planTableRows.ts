/**
 * lib/planTableRows.ts
 * ====================
 * Разбивка строк таблицы плана (выдача/сдача) — встроенная трансформация.
 *
 * «Выдача» строится по входу: одна строка на группу, кол-во =
 * `planned_quantity` (сумма по задачам группы).
 * «Сдача» — по выходам: строка на каждый `outputs[i]` трансформирующего
 * задания (ADR-0002), кол-во = `outputs[i].quantity`; прогресс строки —
 * из `outputs_progress[i]` (Сделано = `produced_quantity`, Передано =
 * нетто-переданное по (задача, размер выхода) из ledger). Нетрансформирующее
 * задание — одна строка (само задание).
 *
 * Разбивка по выходам — встроенная (не критерий профиля группировки),
 * одинаковая в модалке и печати (тикет #95).
 */

import type { SectionBoardTask, TaskGroup } from "@/shared/api/shopfloor";
import { taskGroupingDimensions } from "./groupTasksByProfile";

export type PlanTableMode = "issue" | "handover";

/** Строка таблицы плана после разбивки (по входу или по выходу). */
export type PlanRow = {
  key: string;
  /** Ключ группы, из которой разбита строка (для скрытия группы целиком). */
  groupKey: string;
  /** Первая задача группы (для артикула/операции/маршрута). */
  task: SectionBoardTask;
  /** Габарит строки: вход для «Выдачи», выход для «Сдачи». */
  dimensions: Record<string, unknown> | null;
  /** План по строке. */
  planQty: number;
  /** Сделано по строке. */
  doneQty: number;
  /** Выдано по строке (только «Выдача»). */
  issuedQty: number;
  /** Передано по строке. */
  transferredQty: number;
  /** Остаток = план − сделано. */
  balanceQty: number;
  /** «Заказов»: для выдачи — число задач группы, для сдачи — число заданий, давших выход. */
  ordersCount: number;
};

function toQty(value: string | number | null | undefined): number {
  const n = typeof value === "number" ? value : parseFloat(String(value ?? "0"));
  return Number.isFinite(n) ? n : 0;
}

/** Задание «дало выход», если по нему уже оприходован факт (завершение/выход). */
function taskGivesOutput(task: SectionBoardTask): boolean {
  if (task.transforms_dimensions) {
    return (task.outputs_progress ?? []).some((row) => toQty(row.produced_quantity) > 0);
  }
  return toQty(task.cache.completed_quantity) > 0;
}

/** Прогресс выхода по индексу; fallback по row_number на случай рассинхрона. */
function outputProgressAt(
  task: SectionBoardTask,
  index: number,
  rowNumber: number | null | undefined,
) {
  const progress = task.outputs_progress ?? [];
  if (progress[index]) return progress[index];
  if (rowNumber != null) {
    return progress.find((row) => row.row_number === rowNumber);
  }
  return undefined;
}

/** Строки «Выдачи»: одна строка на группу (по входу). */
function buildIssueRows(groups: TaskGroup[]): PlanRow[] {
  const rows: PlanRow[] = [];
  for (const group of groups) {
    const task = group.tasks[0];
    const issued = group.tasks.reduce(
      (s, t) => s + toQty(t.cache.issued_quantity),
      0,
    );
    rows.push({
      key: `${group.key}__issue`,
      groupKey: group.key,
      task,
      dimensions: taskGroupingDimensions(task),
      planQty: group.totalQtyPlan,
      doneQty: group.totalQtyDone,
      issuedQty: issued,
      transferredQty: group.tasks.reduce(
        (s, t) => s + toQty(t.cache.transferred_quantity),
        0,
      ),
      balanceQty: group.totalQtyPlan - group.totalQtyDone,
      ordersCount: group.tasks.length,
    });
  }
  return rows;
}

/** Строки «Сдачи»: строка на каждый выход трансформирующего задания. */
function buildHandoverRows(groups: TaskGroup[]): PlanRow[] {
  const rows: PlanRow[] = [];
  for (const group of groups) {
    const ordersCount = group.tasks.filter(taskGivesOutput).length;
    for (const task of group.tasks) {
      if (task.transforms_dimensions && task.outputs?.length) {
        task.outputs.forEach((out, index) => {
          const progress = outputProgressAt(task, index, out.row_number);
          const planQty = toQty(out.quantity);
          const doneQty = toQty(progress?.produced_quantity);
          const transferredQty = toQty(progress?.transferred_quantity);
          rows.push({
            key: `${group.key}__out${index}__${task.id}`,
            groupKey: group.key,
            task,
            dimensions: out.dimensions ?? null,
            planQty,
            doneQty,
            issuedQty: 0,
            transferredQty,
            balanceQty: planQty - doneQty,
            ordersCount,
          });
        });
        continue;
      }
      const planQty = toQty(task.planned_quantity);
      rows.push({
        key: `${group.key}__${task.id}`,
        groupKey: group.key,
        task,
        dimensions: taskGroupingDimensions(task),
        planQty,
        doneQty: toQty(task.cache.completed_quantity),
        issuedQty: toQty(task.cache.issued_quantity),
        transferredQty: toQty(task.cache.transferred_quantity),
        balanceQty: planQty - toQty(task.cache.completed_quantity),
        ordersCount,
      });
    }
  }
  return rows;
}

/** Разбивка групп на строки плана по режиму (выдача/сдача). */
export function buildPlanRows(
  groups: TaskGroup[],
  mode: PlanTableMode,
): PlanRow[] {
  return mode === "issue" ? buildIssueRows(groups) : buildHandoverRows(groups);
}
