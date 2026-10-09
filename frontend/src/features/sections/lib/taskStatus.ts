import type { SectionBoardTask } from "@/shared/api/shopfloor";
import type { ActionReasonCode } from "@/shared/lib/actionReasons";
import type { RowTone } from "@/shared/lib/rowTones";
import { taskStatusLabels } from "@/shared/lib/generated-labels";

export { taskStatusLabels };

const ACTIVE_STATUSES = new Set([
  "ready",
  "in_progress",
  "partially_completed",
  "in_work",
  "partially",
]);

/** Статусы, которые закрывают строку сами по себе, без оглядки на количества. */
const CLOSED_STATUSES = ["completed", "cancelled", "done", "skipped"];
const WAITING_STATUSES = ["waiting_previous", "pending", "blocked"];
const RUNNING_STATUSES = ["in_progress", "in_work"];

export type TaskViewCategory = "active" | "waiting" | "completed";

/**
 * Тон строки — часть общего словаря `shared/lib/rowTones`, его же берут
 * «Передачи». `scrap` (брак) из тонов исключён: на доске брак — поле и пилюля,
 * а не тон строки.
 */
export type TaskTone = Exclude<RowTone, "scrap">;

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

/** Цвета пилюль по статусу. Владелец один — `getTaskRowState`. */
const taskStatusColor: Record<string, string> = {
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

const BADGE_COMPLETE = "bg-emerald-100 text-emerald-700";
const BADGE_TRANSFERRED = "bg-blue-100 text-blue-700";
const BADGE_NOT_TRANSFERRED = "bg-slate-100 text-slate-600";

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

/**
 * Состояние строки задания — одно решение на строку (#324).
 *
 * Категория (фильтры), тон (заливка строки и карточки), подпись, класс пилюли и
 * класс точки статуса считаются здесь вместе, потому что считают одно и то же
 * состояние. Раньше это были пять соседних функций с независимыми ветвями по
 * одним и тем же статусам и тремя маршрутами к «ready»: подпись шла через
 * `getReadyStatusLabel`, пилюля и точка — каждая своим бранчем. Значения
 * сходились, но шаг в сторону у любой из копий менял поведение одного места
 * (так было в ADR-0031: панель массовых операций не считала полностью
 * переданное задание завершённым).
 *
 * `isComplete` и `isRawTransferred` отдаются наружу: это те два вопроса, из
 * которых выведено всё остальное, и раскладке иногда нужен ответ без разбора
 * класса.
 *
 * Точка статуса — известное исключение: она зелёная по `isFullyTransferred`, но
 * не по `isTaskExecutionComplete`, то есть строка со внесённым фактом и статусом
 * «в работе» несёт подпись «Завершен» и жёлтую точку. Так было до этого модуля,
 * вид доски здесь не меняется — расхождение оставлено явным, а не растворено в
 * ветвях.
 */
export type TaskRowState = {
  category: TaskViewCategory;
  /** Факт обработан или план передан целиком — «готово» строки. */
  isComplete: boolean;
  /** Сырьё с предыдущего этапа передано (вопрос строки `ready`). */
  isRawTransferred: boolean;
  tone: TaskTone;
  label: string;
  badgeClass: string;
  dotClass: string;
};

export function getTaskRowState(task: SectionBoardTask): TaskRowState {
  const status = task.status;
  const isFullyTransferred = isTaskFullyTransferred(task);
  const isComplete = isTaskExecutionComplete(task) || isFullyTransferred;
  const isRawTransferred = status === "ready" && getReadyStatusLabel(task) === "Передано";

  let category: TaskViewCategory = "active";
  if (CLOSED_STATUSES.includes(status) || isComplete) category = "completed";
  else if (WAITING_STATUSES.includes(status)) category = "waiting";

  let tone: TaskTone = "active";
  if (category === "completed") tone = "completed";
  else if (category === "waiting") tone = "waiting";
  else if (RUNNING_STATUSES.includes(status)) tone = "activeRunning";

  let label: string;
  if (isComplete) label = "Завершен";
  else if (status === "ready") label = isRawTransferred ? "Передано" : "Не передано";
  else label = taskStatusLabels[status] || status;

  let badgeClass: string;
  if (isComplete || status === "completed" || status === "done") badgeClass = BADGE_COMPLETE;
  else if (status === "ready") {
    badgeClass = isRawTransferred ? BADGE_TRANSFERRED : BADGE_NOT_TRANSFERRED;
  } else badgeClass = taskStatusColor[status] || "";

  let dotClass = "bg-slate-300";
  if (isFullyTransferred) dotClass = "bg-emerald-500";
  else if (RUNNING_STATUSES.includes(status)) dotClass = "bg-amber-500 animate-pulse";
  else if (["ready", "partially_completed", "partially"].includes(status)) {
    dotClass = status === "ready" && !isRawTransferred ? "bg-slate-400" : "bg-blue-500";
  } else if (["completed", "done"].includes(status)) dotClass = "bg-emerald-500";
  else if (status === "blocked") dotClass = "bg-red-500";
  else if (["waiting_previous", "pending"].includes(status)) dotClass = "bg-yellow-400";

  return { category, isComplete, isRawTransferred, tone, label, badgeClass, dotClass };
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
