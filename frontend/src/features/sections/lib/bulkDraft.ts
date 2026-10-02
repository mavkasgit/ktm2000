/**
 * lib/bulkDraft.ts — черновик массового ввода факта на доске участка (#283).
 *
 * Панель массовых операций держала своё состояние групп и раскладывала
 * количество пропорционально плану (`distributeQtyProportional`). Решение
 * гриллинга #263 другое: ввод живёт в строках и шапках групп самой доски,
 * раскладка — последовательная сверху вниз, избыток садится в последнюю
 * строку и помечается «сверх плана». Это правило одно, поэтому и живёт здесь
 * одним модулем, а не в разметке доски и не в компоненте футера.
 *
 * Черновик привязан к `task.id`, а не к позиции строки: смена фильтра и
 * сортировки не двигает введённое у своих заданий. Пустое поле — отсутствие
 * ввода, а не ноль (ADR-0032), поэтому пустая строка хранится как пустая и
 * задача без значений из черновика выпадает.
 */

import type { SectionBoardTask } from "@/shared/api/shopfloor";
import { toQtyInteger } from "@/shared/lib/quantityFormat";

import { isTaskCompletable } from "./taskStatus";

/** Поле ввода факта: годные штуки или брак. */
export type DraftField = "good" | "defect";

export type DraftQty = { good: string; defect: string };

/** Черновик по id задачи: у задачи без ввода записи нет. */
export type BulkDraft = Readonly<Record<number, DraftQty>>;

export const EMPTY_DRAFT_QTY: DraftQty = { good: "", defect: "" };

/** Черновик задачи; у задачи без ввода — пустая пара. */
export function draftQtyFor(draft: BulkDraft, taskId: number): DraftQty {
  return draft[taskId] ?? EMPTY_DRAFT_QTY;
}

function hasValue(qty: DraftQty): boolean {
  return qty.good.trim() !== "" || qty.defect.trim() !== "";
}

/** Есть ли в черновике хоть одно введённое количество. */
export function isDraftEmpty(draft: BulkDraft): boolean {
  for (const qty of Object.values(draft)) {
    if (hasValue(qty)) return false;
  }
  return true;
}

/** Итог черновика: сколько годных и брака «к записи» и по скольким заданиям. */
export function draftTotals(draft: BulkDraft): { good: number; defect: number; tasks: number } {
  let good = 0;
  let defect = 0;
  let tasks = 0;
  for (const qty of Object.values(draft)) {
    if (!hasValue(qty)) continue;
    tasks += 1;
    good += toQtyInteger(qty.good);
    defect += toQtyInteger(qty.defect);
  }
  return { good, defect, tasks };
}

/**
 * Черновик после правки одной ячейки. Пустое значение убирает запись целиком:
 * «нет ввода» и «ноль» — разные состояния поля (ADR-0032), и без этого футер
 * считал бы «к записи» по задаче, в которую оператор ничего не вводил.
 */
export function withDraftField(
  draft: BulkDraft,
  taskId: number,
  field: DraftField,
  value: string,
): BulkDraft {
  const current = draftQtyFor(draft, taskId);
  const next: DraftQty = { ...current, [field]: value };
  if (!hasValue(next)) {
    if (!(taskId in draft)) return draft;
    const result = { ...draft };
    delete result[taskId];
    return result;
  }
  return { ...draft, [taskId]: next };
}

/** Убирает из черновика перечисленные задания (снятое выделение и т. п.). */
export function withoutDraftIds(draft: BulkDraft, ids: Iterable<number>): BulkDraft {
  const result = { ...draft };
  let changed = false;
  for (const id of ids) {
    if (id in result) {
      delete result[id];
      changed = true;
    }
  }
  return changed ? result : draft;
}

/** Трансформирующий этап (ADR-0002): факт считается в заготовках входа. */
export function isTransformTask(task: SectionBoardTask): boolean {
  return Boolean(task.transforms_dimensions) && (task.outputs?.length ?? 0) > 0;
}

/** В работе: выданное минус уже записанный факт; у раскроя — остаток входа. */
export function taskInWork(task: SectionBoardTask): number {
  const rejected = toQtyInteger(task.cache.rejected_quantity);
  if (isTransformTask(task)) {
    return Math.max(
      0,
      toQtyInteger(task.input_quantity ?? "0") -
        toQtyInteger(task.input_consumed_quantity ?? "0") -
        rejected,
    );
  }
  return Math.max(
    0,
    toQtyInteger(task.cache.issued_quantity) -
      toQtyInteger(task.cache.completed_quantity) -
      rejected,
  );
}

/**
 * Потолок строки: сколько по задаче записывается без дефицита. Это «доступно
 * на задачу»: в работе плюс то, что участок может довыдать. У раскроя потолок
 * — остаток входа: входные заготовки не довыдаются, а стратегия дефицита к
 * трансформирующему этапу не применяется вовсе (ADR-0002).
 */
export function taskFactCeiling(task: SectionBoardTask): number {
  if (isTransformTask(task)) return taskInWork(task);
  return taskInWork(task) + Math.max(0, toQtyInteger(task.cache.available_quantity));
}

export type DistributedQty = {
  taskId: number;
  value: number;
  /** Избыток, который не влез ни в одну строку, — садится в последнюю. */
  overPlan: boolean;
};

/**
 * Последовательная раскладка количества по строкам: сверху вниз, потолок
 * строки — доступное на задачу. Избыток не теряется: садится в последнюю
 * строку и помечается «сверх плана». Пропорциональной раскладки панели
 * (`distributeQtyProportional`) здесь нет намеренно: одно и то же количество
 * в группе и в диалоге давало разный результат, а последовательность видна
 * оператору прямо в строках.
 */
export function distributeSequential(
  tasks: SectionBoardTask[],
  total: number,
): DistributedQty[] {
  const result: DistributedQty[] = tasks.map((task) => ({
    taskId: task.id,
    value: 0,
    overPlan: false,
  }));
  if (tasks.length === 0) return result;

  let remaining = Math.max(0, toQtyInteger(total));
  for (let index = 0; index < tasks.length; index++) {
    const value = Math.min(remaining, taskFactCeiling(tasks[index]));
    result[index].value = value;
    remaining -= value;
  }
  if (remaining > 0) {
    const last = result[result.length - 1];
    last.value += remaining;
    last.overPlan = true;
  }
  return result;
}

/**
 * Черновик после ввода в поле группы: введённое раскладывается по строкам
 * группы. Очистка поля (пустая строка) возвращает строкам плейсхолдеры, а не
 * нули: ноль — это записанный факт, пустое поле — его отсутствие.
 */
export function applyGroupField(
  draft: BulkDraft,
  tasks: SectionBoardTask[],
  field: DraftField,
  rawValue: string,
): BulkDraft {
  let next = draft;
  if (rawValue.trim() === "") {
    for (const task of tasks) next = withDraftField(next, task.id, field, "");
    return next;
  }
  const distributed = distributeSequential(tasks, toQtyInteger(rawValue));
  const total = distributed.reduce((sum, row) => sum + row.value, 0);
  for (const row of distributed) {
    // Строка, которой ничего не досталось, остаётся пустой: «0» — это
    // записанный факт, и заводить его там, где оператор ничего не вводил,
    // значило бы показать в поле группы ноль вместо плейсхолдера.
    next = withDraftField(next, row.taskId, field, total === 0 || row.value > 0 ? String(row.value) : "");
  }
  return next;
}

export type DraftShortage = { fact: number; limit: number; excess: number };

/**
 * Дефицит черновика: сумма факта и брака превышает доступный лимит. `null` —
 * дефицита нет. Раскрой в счёт не входит: его лимит — остаток входа, а не
 * сумма потолков, и стратегия дефицита к нему не применяется (ADR-0002).
 */
export function draftShortage(
  tasks: SectionBoardTask[],
  draft: BulkDraft,
): DraftShortage | null {
  let fact = 0;
  let limit = 0;
  for (const task of tasks) {
    // Недоводимые строки в пачку не уедут (`draftEntries`), поэтому и дефицит
    // по ним не считается: иначе футер требовал бы стратегию для расхождения,
    // которого в записи не будет.
    if (!isTaskCompletable(task)) continue;
    const qty = draftQtyFor(draft, task.id);
    const taskFact = toQtyInteger(qty.good) + toQtyInteger(qty.defect);
    if (taskFact <= 0 || isTransformTask(task)) continue;
    fact += taskFact;
    limit += taskFactCeiling(task);
  }
  const excess = fact - limit;
  return excess > 0 ? { fact, limit, excess } : null;
}

export type DraftEntry = { taskId: number; goodQty: string; defectQty: string };

/**
 * Пачка записей из черновика: одна entry на задачу (`bulkCompleteTasks`).
 * Задания без введённого количества в пачку не попадают, а недоводимые
 * (ожидают сырья, отменены, уже завершены) возвращаются отдельным списком —
 * футер говорит о них оператору, а не молча теряет ввод.
 */
export function draftEntries(
  tasks: SectionBoardTask[],
  draft: BulkDraft,
): { entries: DraftEntry[]; skipped: SectionBoardTask[] } {
  const entries: DraftEntry[] = [];
  const skipped: SectionBoardTask[] = [];
  for (const task of tasks) {
    const qty = draftQtyFor(draft, task.id);
    const good = toQtyInteger(qty.good);
    const defect = toQtyInteger(qty.defect);
    if (good <= 0 && defect <= 0) continue;
    if (!isTaskCompletable(task)) {
      skipped.push(task);
      continue;
    }
    entries.push({ taskId: task.id, goodQty: String(good), defectQty: String(defect) });
  }
  return { entries, skipped };
}

/** Итог пачки «к записи» — счётчики футера считаются по тому, что уедет. */
export function draftEntryTotals(entries: DraftEntry[]): { good: number; defect: number } {
  let good = 0;
  let defect = 0;
  for (const entry of entries) {
    good += toQtyInteger(entry.goodQty);
    defect += toQtyInteger(entry.defectQty);
  }
  return { good, defect };
}
