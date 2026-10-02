import type { SectionBoardTask } from "@/shared/api/shopfloor";
import type { ActionReasonCode } from "@/shared/lib/actionReasons";
import { taskStatusLabels } from "@/shared/lib/generated-labels";

export { taskStatusLabels };

const ACTIVE_STATUSES = new Set([
  "ready",
  "in_progress",
  "partially_completed",
  "in_work",
  "partially",
]);

export type TaskViewCategory = "active" | "waiting" | "completed";

/** Задание, по которому весь выданный материал обработан. */
export function isTaskExecutionComplete(task: SectionBoardTask): boolean {
  if (task.transforms_dimensions) {
    const input = parseFloat(task.input_quantity ?? "0") || 0;
    const consumed = parseFloat(task.input_consumed_quantity ?? "0") || 0;
    const rejected = parseFloat(task.cache.rejected_quantity) || 0;
    return input > 0 && consumed + rejected >= input;
  }

  const issued = parseFloat(task.cache.issued_quantity) || 0;
  const processed =
    (parseFloat(task.cache.completed_quantity) || 0) +
    (parseFloat(task.cache.rejected_quantity) || 0);
  return issued > 0 && processed >= issued;
}

/** Задача передала весь план, но формально ещё не закрыта (status != completed). */
export function isTaskFullyTransferred(task: SectionBoardTask): boolean {
  if (!ACTIVE_STATUSES.has(task.status)) return false;
  // Для трансформации remaining_quantity относится к выходному объёму,
  // а не к входным заготовкам. После получения входа остаток может быть 0
  // ещё до завершения раскроя, поэтому задача остаётся активной.
  if (task.transforms_dimensions) return false;
  const remaining = parseFloat(task.cache.remaining_quantity) || 0;
  return remaining <= 0;
}

/** Категория для фильтров «Активные / Ожидают / Завершенные» на доске участка. */
export function getTaskViewCategory(task: SectionBoardTask): TaskViewCategory {
  // skipped — закрытый этап (#207): материал подан в готовом виде, этап
  // не выполнялся, но он и не отменён.
  if (["completed", "cancelled", "done", "skipped"].includes(task.status)) return "completed";
  if (isTaskExecutionComplete(task) || isTaskFullyTransferred(task)) return "completed";
  if (["waiting_previous", "pending", "blocked"].includes(task.status)) return "waiting";
  if (ACTIVE_STATUSES.has(task.status)) return "active";
  return "active";
}

export const taskStatusColor: Record<string, string> = {
  waiting_previous: "bg-gray-100 text-gray-600",
  ready: "bg-blue-100 text-blue-700",
  in_progress: "bg-amber-100 text-amber-700",
  partially_completed: "bg-orange-100 text-orange-700",
  completed: "bg-emerald-100 text-emerald-700",
  cancelled: "bg-red-100 text-red-600",
  skipped: "bg-slate-100 text-slate-600",
  pending: "bg-gray-100 text-gray-600",
  in_work: "bg-amber-100 text-amber-700",
  done: "bg-emerald-100 text-emerald-700",
  partially: "bg-orange-100 text-orange-700",
  blocked: "bg-red-100 text-red-600",
};

// Для статуса "ready" отображаем фактическое состояние передачи сырья
// с предыдущего участка, а не обобщённое "К выдаче".
// Если с предыдущего этапа уже передано > 0 — "Передано",
// иначе — "Не передано" (если previous_stage отсутствует, считаем 0).
export function getReadyStatusLabel(task: SectionBoardTask): "Передано" | "Не передано" {
  const transferred = task.previous_stage
    ? parseFloat(task.previous_stage.transferred_quantity) || 0
    : 0;
  return transferred > 0 ? "Передано" : "Не передано";
}

export function getStatusLabel(task: SectionBoardTask): string {
  if (isTaskExecutionComplete(task) || isTaskFullyTransferred(task)) return "Завершен";
  if (task.status === "ready") return getReadyStatusLabel(task);
  return taskStatusLabels[task.status] || task.status;
}

export function getStatusColor(task: SectionBoardTask): string {
  if (isTaskExecutionComplete(task) || isTaskFullyTransferred(task) || ["completed", "done"].includes(task.status)) {
    return "bg-emerald-100 text-emerald-700";
  }
  if (task.status === "ready") {
    return getReadyStatusLabel(task) === "Передано"
      ? "bg-blue-100 text-blue-700"
      : "bg-slate-100 text-slate-600";
  }
  return taskStatusColor[task.status] || "";
}

/**
 * Причина, по которой задание нельзя завершить, — код из общего словаря
 * причин (#193). `null` — завершать можно.
 *
 * Предикат и причина объявлены одной функцией: раньше это были два независимых
 * списка, и они разошлись — статус `skipped` закрывал завершение, но причины
 * не имел, поэтому кнопка гасла без объяснения.
 */
export function getCompletionBlockReason(task: SectionBoardTask): ActionReasonCode | null {
  if (task.status === "waiting_previous") return "awaiting_raw";
  if (task.status === "ready" && getReadyStatusLabel(task) === "Не передано") return "raw_not_received";
  if (["completed", "done"].includes(task.status)) return "already_completed";
  if (task.status === "cancelled") return "cancelled";
  if (task.status === "skipped") return "stage_skipped";
  if (isTaskExecutionComplete(task)) return "fact_entered";
  return null;
}

export function isTaskCompletable(task: SectionBoardTask): boolean {
  return getCompletionBlockReason(task) === null;
}

/**
 * Незавершаемые задания, сгруппированные по причине: футер массового ввода
 * говорит ими, что часть введённого количества записано не будет. Раньше
 * список собирали вручную и делили надвое («Не передано» / «Прочие — ожидают
 * сырья или уже завершены»), из-за чего формулировка расходилась с кнопкой
 * доски.
 */
export function groupTasksByBlockReason(
  tasks: SectionBoardTask[],
): { reason: ActionReasonCode; tasks: SectionBoardTask[] }[] {
  const groups = new Map<ActionReasonCode, SectionBoardTask[]>();
  for (const task of tasks) {
    const reason = getCompletionBlockReason(task);
    if (!reason) continue;
    const bucket = groups.get(reason);
    if (bucket) bucket.push(task);
    else groups.set(reason, [task]);
  }
  return Array.from(groups, ([reason, grouped]) => ({ reason, tasks: grouped }));
}
