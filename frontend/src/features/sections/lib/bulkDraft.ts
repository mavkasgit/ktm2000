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
import { fmtQty, toQtyInteger } from "@/shared/lib/quantityFormat";
import { parseQuantityInput, type QuantityInputMode } from "@/shared/lib/quantityInput";

import { isTaskCompletable } from "./taskStatus";
import {
  factPortion,
  resolveFactQuantity,
  type FactQuantityResolution,
} from "./factQuantity";

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

/** Записанный факт строки по колонке: годные или брак. */
export function recordedFact(task: SectionBoardTask, field: DraftField): number {
  return toQtyInteger(
    field === "good" ? task.cache.completed_quantity : task.cache.rejected_quantity,
  );
}

/**
 * Записанный факт группы по колонке. Единственное место, где факт группы
 * считается: от него зависят и плейсхолдер поля («сейчас N»), и разбор ввода
 * («факт станет N»). Две разные базы читались бы как две правды — плейсхолдер
 * «сейчас 3» при фактически записанных 2 отправляет оператора в цель, которую
 * сервер отвергнет.
 */
export function groupRecordedFact(tasks: SectionBoardTask[], field: DraftField): number {
  return tasks.reduce((sum, task) => sum + recordedFact(task, field), 0);
}

/** Разрешение ввода строки по колонке: порция, режим, записанное и итог. */
export function resolveDraftField(
  task: SectionBoardTask,
  draft: BulkDraft,
  field: DraftField,
): FactQuantityResolution {
  return resolveFactQuantity(draftQtyFor(draft, task.id)[field], recordedFact(task, field));
}

/**
 * Итог черновика по выбранным заданиям: сколько «к записи» (порциями, а не
 * набранными числами: «факт станет 500» при записанных 400 — это порция 100)
 * и по скольким заданиям есть ввод.
 */
export function draftTotals(
  tasks: SectionBoardTask[],
  draft: BulkDraft,
): { good: number; defect: number; tasks: number } {
  let good = 0;
  let defect = 0;
  let withInput = 0;
  for (const task of tasks) {
    const qty = draftQtyFor(draft, task.id);
    if (!hasValue(qty)) continue;
    withInput += 1;
    good += factPortion(qty.good, recordedFact(task, "good"));
    defect += factPortion(qty.defect, recordedFact(task, "defect"));
  }
  return { good, defect, tasks: withInput };
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
 * Разрешение ввода в поле группы: записанное по всем строкам и порция к
 * раскладке. «Факт группы станет N» считается от суммы записанного по строкам —
 * той же базы, что видит оператор в итоге группы.
 */
export function resolveGroupFact(
  tasks: SectionBoardTask[],
  field: DraftField,
  input: string,
): { recorded: number; resolution: FactQuantityResolution } {
  const recorded = groupRecordedFact(tasks, field);
  return { recorded, resolution: resolveFactQuantity(input, recorded) };
}

/**
 * Значение поля группы, выведенное из строк, а не хранимое отдельно: так
 * набранное и разложенное не расходятся, и правка отдельной строки видна в
 * шапке. Форма — та же, что набрал оператор: «+N» для добавки и «N» для цели
 * (когда все строки в режиме «факт станет»). Смешанные режимы показываются
 * порцией со знаком: это то, что уедет, и оно одно на обе формы.
 */
export function groupDraftValue(
  tasks: SectionBoardTask[],
  draft: BulkDraft,
  field: DraftField,
): string {
  const rows = tasks
    .map((task) => draftQtyFor(draft, task.id)[field])
    .filter((value) => value.trim() !== "");
  if (rows.length === 0) return "";

  let portion = 0;
  let target = 0;
  for (const task of tasks) {
    const resolution = resolveDraftField(task, draft, field);
    if (resolution.kind !== "write") continue;
    portion += resolution.quantity;
    target += resolution.target;
  }
  const allSet = rows.every((value) => parseQuantityInput(value).mode === "set");
  return allSet ? String(target) : `+${portion}`;
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
  const { resolution } = resolveGroupFact(tasks, field, rawValue);
  // Ввод, который применить нельзя (цель ниже записанного), не раскладывается:
  // набранное остаётся в поле группы, а причину показывает поле.
  if (resolution.kind !== "write") return next;

  const distributed = distributeSequential(tasks, resolution.quantity);
  const total = distributed.reduce((sum, row) => sum + row.value, 0);
  for (const row of distributed) {
    const task = tasks.find((item) => item.id === row.taskId);
    // «Факт станет N» раскладывается целями (`записано + порция`), «+N» —
    // порциями со знаком: иначе поле строки потеряло бы режим, который набрал
    // оператор, и «500» в строке читалось бы как добавка 500.
    const value =
      resolution.mode === "set" && task
        ? String(recordedFact(task, field) + row.value)
        : `+${row.value}`;
    // Строка, которой ничего не досталось, остаётся пустой: «0» — это
    // записанный факт, и заводить его там, где оператор ничего не вводил,
    // значило бы показать в поле группы ноль вместо плейсхолдера. Порция, равная
    // нулю (набрано «+0» или цель, совпавшая с записанным), ввода не создаёт
    // вовсе: черновик без записи иначе просил бы подтверждение выхода из
    // режима ради пустоты, а футер отвечал бы «введите количество» при
    // заполненных полях.
    next = withDraftField(next, row.taskId, field, row.value > 0 ? value : "");
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
    const taskFact =
      factPortion(qty.good, recordedFact(task, "good")) +
      factPortion(qty.defect, recordedFact(task, "defect"));
    if (taskFact <= 0 || isTransformTask(task)) continue;
    fact += taskFact;
    limit += taskFactCeiling(task);
  }
  const excess = fact - limit;
  return excess > 0 ? { fact, limit, excess } : null;
}

/** Запись по колонке: порция к записи и как её показать оператору. */
export type DraftEntryField = {
  /** Порция — то, что уедет в `good_quantity`/`defect_quantity`. */
  quantity: number;
  mode: QuantityInputMode;
  /** Записанный факт до записи. */
  recorded: number;
  /** Факт после записи. */
  target: number;
};

export type DraftEntry = {
  taskId: number;
  good: DraftEntryField;
  defect: DraftEntryField;
};

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
    if (!hasValue(qty)) continue;
    if (!isTaskCompletable(task)) {
      skipped.push(task);
      continue;
    }
    const good = resolveDraftField(task, draft, "good");
    const defect = resolveDraftField(task, draft, "defect");
    const entry = toDraftEntry(task.id, good, defect);
    // Задание, у которого ввод не применяется (цель ниже записанного) или
    // порции нулевые, в пачку не попадает — как и прежде.
    if (entry.good.quantity <= 0 && entry.defect.quantity <= 0) continue;
    entries.push(entry);
  }
  return { entries, skipped };
}

/** Разрешение вводов задачи в запись; неприменимый ввод считается нулевой порцией. */
function toDraftEntry(
  taskId: number,
  good: FactQuantityResolution,
  defect: FactQuantityResolution,
): DraftEntry {
  const field = (resolution: FactQuantityResolution): DraftEntryField => {
    if (resolution.kind === "write") {
      return {
        quantity: resolution.quantity,
        mode: resolution.mode,
        recorded: resolution.target - resolution.quantity,
        target: resolution.target,
      };
    }
    return { quantity: 0, mode: "add", recorded: 0, target: 0 };
  };
  return { taskId, good: field(good), defect: field(defect) };
}

/**
 * Показ записи по колонке: «+100» — добавка, «400 → 500» — «факт станет 500»
 * (когда вся колонка набрана в этом режиме), «+N» — смешанные режимы: тогда
 * честно то, что уедет, а не то, что набрано.
 */
export function draftEntryFieldSummary(entries: DraftEntry[], field: DraftField): string {
  let portion = 0;
  let recorded = 0;
  let target = 0;
  let allSet = true;
  let filled = false;
  for (const entry of entries) {
    const item = entry[field];
    if (item.quantity <= 0) continue;
    filled = true;
    portion += item.quantity;
    recorded += item.recorded;
    target += item.target;
    if (item.mode !== "set") allSet = false;
  }
  if (!filled) return fmtQty(0);
  return allSet ? `${fmtQty(recorded)} → ${fmtQty(target)}` : `+${fmtQty(portion)}`;
}

/** Итог пачки «к записи» — счётчики футера считаются по тому, что уедет. */
export function draftEntryTotals(entries: DraftEntry[]): { good: number; defect: number } {
  let good = 0;
  let defect = 0;
  for (const entry of entries) {
    good += entry.good.quantity;
    defect += entry.defect.quantity;
  }
  return { good, defect };
}
