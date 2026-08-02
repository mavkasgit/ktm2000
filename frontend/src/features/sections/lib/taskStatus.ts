import type { SectionBoardTask } from "@/shared/api/shopfloor";
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

/** Задача передала весь план, но формально ещё не закрыта (status != completed). */
export function isTaskFullyTransferred(task: SectionBoardTask): boolean {
  if (!ACTIVE_STATUSES.has(task.status)) return false;
  const remaining = parseFloat(task.cache.remaining_quantity) || 0;
  return remaining <= 0;
}

/** Категория для фильтров «Активные / Ожидают / Завершенные» на доске участка. */
export function getTaskViewCategory(task: SectionBoardTask): TaskViewCategory {
  if (["completed", "cancelled", "done"].includes(task.status)) return "completed";
  if (isTaskFullyTransferred(task)) return "completed";
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
  if (isTaskFullyTransferred(task)) return "Завершен";
  if (task.status === "ready") return getReadyStatusLabel(task);
  return taskStatusLabels[task.status] || task.status;
}

export function getStatusColor(task: SectionBoardTask): string {
  if (isTaskFullyTransferred(task) || ["completed", "done"].includes(task.status)) {
    return "bg-emerald-100 text-emerald-700";
  }
  if (task.status === "ready") {
    return getReadyStatusLabel(task) === "Передано"
      ? "bg-blue-100 text-blue-700"
      : "bg-slate-100 text-slate-600";
  }
  return taskStatusColor[task.status] || "";
}

export function isTaskCompletable(task: SectionBoardTask): boolean {
  if (task.status === "waiting_previous") return false;
  if (task.status === "ready" && getReadyStatusLabel(task) === "Не передано") return false;
  if (["completed", "cancelled", "done"].includes(task.status)) return false;
  return true;
}

export function getCompletionDisabledReason(task: SectionBoardTask): string | null {
  if (task.status === "waiting_previous") {
    return "Нельзя завершить задание: ожидает передачи сырья с предыдущего участка";
  }
  if (task.status === "ready" && getReadyStatusLabel(task) === "Не передано") {
    return "Нельзя завершить задание: сырьё ещё не передано с предыдущего участка";
  }
  if (["completed", "cancelled", "done"].includes(task.status)) {
    return "Задание уже завершено";
  }
  return null;
}

// Список задач, которые не будут завершены при групповой операции
// (статус "ready" + "Не передано", а также уже завершённые/отменённые/ожидающие).
export function getNonCompletableTasks(
  tasks: SectionBoardTask[],
): SectionBoardTask[] {
  return tasks.filter((t) => !isTaskCompletable(t));
}
