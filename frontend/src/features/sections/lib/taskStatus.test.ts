import { describe, expect, it } from "vitest";
import type { SectionBoardTask } from "@/shared/api/shopfloor";
import {
  getCompletionBlockReason,
  getReadyStatusLabel,
  getTaskRowState,
  isTaskCompletable,
  isTaskFullyTransferred,
  groupTasksByBlockReason,
  type TaskTone,
  type TaskViewCategory,
} from "./taskStatus";

function makeTask(overrides: Partial<SectionBoardTask> = {}): SectionBoardTask {
  return {
    id: 1,
    product_id: 1,
    product_sku: "TEST-1",
    section_plan_line_id: 1,
    plan_position_id: 1,
    route_step_id: 1,
    sequence: 1,
    operation_code: null,
    operation_name: "Операция",
    is_significant: false,
    planned_quantity: "100",
    status: "ready",
    cache: {
      available_quantity: "0",
      issued_quantity: "0",
      completed_quantity: "0",
      transferred_quantity: "0",
      received_quantity: "0",
      rejected_quantity: "0",
      remaining_quantity: "100",
    },
    previous_stage: null,
    next_task_id: null,
    next_task_status: null,
    next_operation_name: null,
    source_ref: null,
    source_payload: {},
    source_fingerprint: null,
    input_sku: "TEST-1",
    output_sku: "TEST-1",
    display_sku: "TEST-1",
    route_history: [],
    route_history_after: [],
    route_history_full: [],
    route_history_after_full: [],
    operation_codes: [null],
    operation_names: ["Операция"],
    ...overrides,
  };
}

describe("getReadyStatusLabel", () => {
  it("возвращает «Не передано», если previous_stage отсутствует", () => {
    const task = makeTask({ status: "ready", previous_stage: null });
    expect(getReadyStatusLabel(task)).toBe("Не передано");
  });

  it("возвращает «Не передано», если previous_stage.transferred_quantity = 0", () => {
    const task = makeTask({
      status: "ready",
      previous_stage: {
        section_plan_line_id: 1,
        completed_quantity: "0",
        transferred_quantity: "0",
        received_quantity: "0",
      },
    });
    expect(getReadyStatusLabel(task)).toBe("Не передано");
  });

  it("возвращает «Передано», если previous_stage.transferred_quantity > 0", () => {
    const task = makeTask({
      status: "ready",
      previous_stage: {
        section_plan_line_id: 1,
        completed_quantity: "100",
        transferred_quantity: "216",
        received_quantity: "216",
      },
    });
    expect(getReadyStatusLabel(task)).toBe("Передано");
  });
});

describe("getTaskRowState: подпись", () => {
  it("полностью переданная ready-задача → «Завершен»", () => {
    const task = makeTask({
      status: "ready",
      cache: {
        available_quantity: "0",
        issued_quantity: "216",
        completed_quantity: "216",
        transferred_quantity: "216",
        received_quantity: "216",
        rejected_quantity: "0",
        remaining_quantity: "0",
      },
    });
    expect(getTaskRowState(task).label).toBe("Завершен");
  });

  it("для ready подставляет «Передано»/«Не передано»", () => {
    const transferred = makeTask({
      status: "ready",
      previous_stage: {
        section_plan_line_id: 1,
        completed_quantity: "0",
        transferred_quantity: "10",
        received_quantity: "10",
      },
    });
    expect(getTaskRowState(transferred).label).toBe("Передано");
    expect(getTaskRowState(makeTask({ status: "ready" })).label).toBe("Не передано");
  });

  it("для остальных статусов использует карту лейблов", () => {
    expect(getTaskRowState(makeTask({ status: "in_progress" })).label).toBe("В работе");
    expect(getTaskRowState(makeTask({ status: "completed" })).label).toBe("Завершен");
    expect(getTaskRowState(makeTask({ status: "cancelled" })).label).toBe("Отменен");
  });
});

describe("getTaskRowState: класс пилюли", () => {
  it("ready + Передано → синий", () => {
    const t = makeTask({
      status: "ready",
      previous_stage: {
        section_plan_line_id: 1,
        completed_quantity: "0",
        transferred_quantity: "5",
        received_quantity: "5",
      },
    });
    expect(getTaskRowState(t).badgeClass).toContain("blue");
  });

  it("ready + Не передано → серый", () => {
    expect(getTaskRowState(makeTask({ status: "ready" })).badgeClass).toContain("slate");
  });

  it("in_progress → янтарный", () => {
    expect(getTaskRowState(makeTask({ status: "in_progress" })).badgeClass).toContain("amber");
  });
});

describe("isTaskCompletable", () => {
  it("waiting_previous → false", () => {
    expect(isTaskCompletable(makeTask({ status: "waiting_previous" }))).toBe(false);
  });

  it("ready + Не передано → false", () => {
    expect(isTaskCompletable(makeTask({ status: "ready" }))).toBe(false);
  });

  it("ready + Передано → true", () => {
    const t = makeTask({
      status: "ready",
      previous_stage: {
        section_plan_line_id: 1,
        completed_quantity: "0",
        transferred_quantity: "10",
        received_quantity: "10",
      },
    });
    expect(isTaskCompletable(t)).toBe(true);
  });

  it("полностью обработанное задание без передачи → не completable", () => {
    const task = makeTask({
      status: "in_progress",
      cache: {
        available_quantity: "0",
        issued_quantity: "200",
        completed_quantity: "200",
        transferred_quantity: "0",
        received_quantity: "0",
        rejected_quantity: "0",
        remaining_quantity: "200",
      },
    });
    expect(isTaskCompletable(task)).toBe(false);
  });

  it("completed/cancelled/done → false", () => {
    expect(isTaskCompletable(makeTask({ status: "completed" }))).toBe(false);
    expect(isTaskCompletable(makeTask({ status: "cancelled" }))).toBe(false);
    expect(isTaskCompletable(makeTask({ status: "done" }))).toBe(false);
  });

  it("in_progress → true", () => {
    expect(isTaskCompletable(makeTask({ status: "in_progress" }))).toBe(true);
  });
});

describe("isTaskFullyTransferred", () => {
  it("ready + остаток 0 → полностью передано", () => {
    const task = makeTask({
      status: "ready",
      cache: {
        available_quantity: "0",
        issued_quantity: "100",
        completed_quantity: "100",
        transferred_quantity: "100",
        received_quantity: "100",
        rejected_quantity: "0",
        remaining_quantity: "0",
      },
      previous_stage: {
        section_plan_line_id: 1,
        completed_quantity: "100",
        transferred_quantity: "100",
        received_quantity: "100",
      },
    });
    expect(isTaskFullyTransferred(task)).toBe(true);
  });

  it("ready + остаток > 0 → ещё в работе", () => {
    expect(isTaskFullyTransferred(makeTask({ status: "ready" }))).toBe(false);
  });

  it("трансформация с нулевым остатком остаётся активной до полного входа", () => {
    const task = makeTask({
      status: "in_progress",
      transforms_dimensions: true,
      input_quantity: "150",
      input_consumed_quantity: "75",
      cache: {
        available_quantity: "0",
        issued_quantity: "150",
        completed_quantity: "75",
        transferred_quantity: "0",
        received_quantity: "150",
        rejected_quantity: "0",
        remaining_quantity: "0",
      },
    });
    expect(isTaskFullyTransferred(task)).toBe(false);
    expect(getTaskRowState(task).category).toBe("active");
  });

  it("completed → не считается «переданным без закрытия»", () => {
    const task = makeTask({
      status: "completed",
      cache: {
        available_quantity: "0",
        issued_quantity: "100",
        completed_quantity: "100",
        transferred_quantity: "100",
        received_quantity: "100",
        rejected_quantity: "0",
        remaining_quantity: "0",
      },
    });
    expect(isTaskFullyTransferred(task)).toBe(false);
  });
});

describe("getTaskRowState: категория", () => {
  it("полностью переданная ready-задача → completed", () => {
    const task = makeTask({
      status: "ready",
      cache: {
        available_quantity: "0",
        issued_quantity: "216",
        completed_quantity: "216",
        transferred_quantity: "216",
        received_quantity: "216",
        rejected_quantity: "0",
        remaining_quantity: "0",
      },
      previous_stage: {
        section_plan_line_id: 1,
        completed_quantity: "216",
        transferred_quantity: "216",
        received_quantity: "216",
      },
    });
    expect(getTaskRowState(task).category).toBe("completed");
  });

  it("ready с остатком → active", () => {
    expect(getTaskRowState(makeTask({ status: "ready" })).category).toBe("active");
  });

  it("полностью обработанное задание без передачи → completed", () => {
    const task = makeTask({
      status: "in_progress",
      cache: {
        available_quantity: "0",
        issued_quantity: "200",
        completed_quantity: "200",
        transferred_quantity: "0",
        received_quantity: "0",
        rejected_quantity: "0",
        remaining_quantity: "200",
      },
    });
    expect(getTaskRowState(task).category).toBe("completed");
  });

  it("частично обработанное задание → active", () => {
    const task = makeTask({
      status: "in_progress",
      cache: {
        available_quantity: "0",
        issued_quantity: "200",
        completed_quantity: "100",
        transferred_quantity: "0",
        received_quantity: "0",
        rejected_quantity: "0",
        remaining_quantity: "200",
      },
    });
    expect(getTaskRowState(task).category).toBe("active");
  });

  it("частично обработанное задание → completable", () => {
    const task = makeTask({
      status: "in_progress",
      cache: {
        available_quantity: "0",
        issued_quantity: "200",
        completed_quantity: "100",
        transferred_quantity: "0",
        received_quantity: "0",
        rejected_quantity: "0",
        remaining_quantity: "200",
      },
    });
    expect(isTaskCompletable(task)).toBe(true);
  });

  it("waiting_previous → waiting", () => {
    expect(getTaskRowState(makeTask({ status: "waiting_previous" })).category).toBe("waiting");
  });
});

/**
 * Таблица состояний: одно утверждение на статус, и оно сразу про категорию, тон,
 * подпись, пилюлю и точку (#324). Раньше это были пять функций с независимыми
 * ветвями и три маршрута к «ready»; новый статус требовал правки в каждом. Теперь
 * новый статус — строка в этой таблице и ветвь в `getTaskRowState`.
 *
 * Точка статуса у «отменено»/«пропущено» серая (`bg-slate-300`) при красной и
 * серой пилюлях — так было до этого модуля, вид доски не меняется; в таблице это
 * зафиксировано явно, чтобы расхождение нельзя было принять за новую регрессию.
 */
describe("getTaskRowState: состояние строки целиком", () => {
  const rows: [
    SectionBoardTask["status"],
    TaskViewCategory,
    TaskTone,
    string,
    string,
    string,
  ][] = [
    ["waiting_previous", "waiting", "waiting", "Ожидает", "bg-gray-100 text-gray-600", "bg-yellow-400"],
    ["pending", "waiting", "waiting", "Ожидает", "bg-gray-100 text-gray-600", "bg-yellow-400"],
    ["blocked", "waiting", "waiting", "Блокировка", "bg-red-100 text-red-600", "bg-red-500"],
    ["ready", "active", "active", "Не передано", "bg-slate-100 text-slate-600", "bg-slate-400"],
    ["in_progress", "active", "activeRunning", "В работе", "bg-amber-100 text-amber-700", "bg-amber-500 animate-pulse"],
    ["in_work", "active", "activeRunning", "В работе", "bg-amber-100 text-amber-700", "bg-amber-500 animate-pulse"],
    ["partially_completed", "active", "active", "Частично", "bg-orange-100 text-orange-700", "bg-blue-500"],
    ["partially", "active", "active", "Частично", "bg-orange-100 text-orange-700", "bg-blue-500"],
    ["completed", "completed", "completed", "Завершен", "bg-emerald-100 text-emerald-700", "bg-emerald-500"],
    ["done", "completed", "completed", "Завершен", "bg-emerald-100 text-emerald-700", "bg-emerald-500"],
    ["cancelled", "completed", "completed", "Отменен", "bg-red-100 text-red-600", "bg-slate-300"],
    ["skipped", "completed", "completed", "Пропущено", "bg-slate-100 text-slate-600", "bg-slate-300"],
  ];

  it.each(rows)(
    "%s → категория, тон, подпись, пилюля и точка одним решением",
    (status, category, tone, label, badgeClass, dotClass) => {
      expect(getTaskRowState(makeTask({ status }))).toEqual({
        category,
        isComplete: false,
        isRawTransferred: false,
        tone,
        label,
        badgeClass,
        dotClass,
      });
    },
  );

  it("ready с переданным сырьём: та же запись, но подпись и цвета «Передано»", () => {
    const task = makeTask({
      status: "ready",
      previous_stage: {
        section_plan_line_id: 1,
        completed_quantity: "0",
        transferred_quantity: "10",
        received_quantity: "10",
      },
    });
    expect(getTaskRowState(task)).toEqual({
      category: "active",
      isComplete: false,
      isRawTransferred: true,
      tone: "active",
      label: "Передано",
      badgeClass: "bg-blue-100 text-blue-700",
      dotClass: "bg-blue-500",
    });
  });

  it("факт обработан — это «готово», но не «сырьё передано»", () => {
    const task = makeTask({
      status: "in_progress",
      cache: {
        available_quantity: "0",
        issued_quantity: "200",
        completed_quantity: "200",
        transferred_quantity: "0",
        received_quantity: "0",
        rejected_quantity: "0",
        remaining_quantity: "200",
      },
    });
    const state = getTaskRowState(task);
    expect(state.isComplete).toBe(true);
    expect(state.isRawTransferred).toBe(false);
    expect(state.label).toBe("Завершен");
  });
});

/** Готовое задание: сырьё с предыдущего этапа передано, факт ещё не внесён. */
function completableTask(overrides: Partial<SectionBoardTask> = {}): SectionBoardTask {
  return makeTask({
    status: "in_progress",
    ...overrides,
  });
}

/** Задание, по которому весь выданный материал уже обработан. */
function fullyProcessedTask(): SectionBoardTask {
  return makeTask({
    status: "in_progress",
    cache: {
      available_quantity: "0",
      issued_quantity: "200",
      completed_quantity: "200",
      transferred_quantity: "0",
      received_quantity: "0",
      rejected_quantity: "0",
      remaining_quantity: "200",
    },
  });
}

/**
 * Код причины по состоянию задания (#193).
 *
 * Это то, что оператор читает рядом с кнопкой «Завершить»: экран берёт текст
 * из словаря по коду, поэтому важна именно пара «состояние → код». Формулировки
 * здесь нет — она в `ACTION_REASON_TEXT`.
 */
describe("getCompletionBlockReason", () => {
  it.each([
    [
      "ожидает предыдущий участок",
      makeTask({ status: "waiting_previous" }),
      "awaiting_raw",
    ],
    [
      "готов, но сырьё с предыдущего этапа не поступило",
      makeTask({ status: "ready", previous_stage: null }),
      "raw_not_received",
    ],
    [
      "готов, сырьё передано нулевым количеством",
      makeTask({
        status: "ready",
        previous_stage: {
          section_plan_line_id: 1,
          completed_quantity: "0",
          transferred_quantity: "0",
          received_quantity: "0",
        },
      }),
      "raw_not_received",
    ],
    ["completed", makeTask({ status: "completed" }), "already_completed"],
    ["cancelled", makeTask({ status: "cancelled" }), "cancelled"],
    ["done", makeTask({ status: "done" }), "already_completed"],
    ["skipped", makeTask({ status: "skipped" }), "stage_skipped"],
    ["весь выданный материал обработан", fullyProcessedTask(), "fact_entered"],
  ] as const)("%s", (_case, task, expected) => {
    expect(getCompletionBlockReason(task)).toBe(expected);
  });

  it.each([
    ["в работе, сырьё есть, факт не внесён", completableTask()],
    [
      "готов и сырьё передано",
      makeTask({
        status: "ready",
        previous_stage: {
          section_plan_line_id: 1,
          completed_quantity: "0",
          transferred_quantity: "10",
          received_quantity: "10",
        },
      }),
    ],
  ] as const)("доступное задание без причины: %s", (_case, task) => {
    expect(getCompletionBlockReason(task)).toBeNull();
  });

  /**
   * Регресс #193: `skipped` закрывал завершение, но кода причины не имел —
   * кнопка гасла без объяснения. Теперь любое задание, чьё завершение
   * заблокировано, обязано объяснять почему.
   */
  it.each([
    ["waiting_previous", makeTask({ status: "waiting_previous" })],
    ["ready без сырья", makeTask({ status: "ready" })],
    ["completed", makeTask({ status: "completed" })],
    ["cancelled", makeTask({ status: "cancelled" })],
    ["done", makeTask({ status: "done" })],
    ["skipped", makeTask({ status: "skipped" })],
    ["факт внесён", fullyProcessedTask()],
  ] as const)("заблокированное задание (%s) гасит кнопку И объясняет причину", (_case, task) => {
    expect(isTaskCompletable(task)).toBe(false);
    expect(getCompletionBlockReason(task)).not.toBeNull();
  });
});

/**
 * Футер массового ввода собирает незавершаемые задания по кодам.
 * Ошибка здесь — тихая: либо в баннер утечёт доступное задание, либо часть
 * незавершаемых потеряется и оператор посчитает, что завершит больше, чем
 * завершится на самом деле.
 */
describe("groupTasksByBlockReason", () => {
  const readyWithRaw = makeTask({
    id: 1,
    status: "ready",
    previous_stage: {
      section_plan_line_id: 1,
      completed_quantity: "0",
      transferred_quantity: "10",
      received_quantity: "10",
    },
  });
  const tasks = [
    makeTask({ id: 1, status: "ready" }),
    makeTask({ id: 2, status: "waiting_previous" }),
    makeTask({ id: 3, status: "completed" }),
    readyWithRaw,
    makeTask({ id: 5, status: "cancelled" }),
    { ...fullyProcessedTask(), id: 6 },
    makeTask({ id: 7, status: "skipped" }),
  ];

  it("раскладывает незавершаемые задания по кодам, доступные не попадают", () => {
    const groups = groupTasksByBlockReason(tasks);

    expect(
      groups.map((group) => [group.reason, group.tasks.map((t) => t.id)]),
    ).toEqual([
      ["raw_not_received", [1]],
      ["awaiting_raw", [2]],
      ["already_completed", [3]],
      ["cancelled", [5]],
      ["fact_entered", [6]],
      ["stage_skipped", [7]],
    ]);
  });

  it("в группе лежат только задания с этой причиной, а их сумма равна числу незавершаемых", () => {
    const nonCompletable = tasks.filter((task) => getCompletionBlockReason(task) !== null);
    const groups = groupTasksByBlockReason(tasks);

    for (const group of groups) {
      // Доступное задание кода не имеет и в баннер попасть не должно: иначе
      // оператор прочитает причину, которой у него на самом деле нет.
      expect(group.reason).not.toBeNull();
      for (const task of group.tasks) {
        expect(getCompletionBlockReason(task)).toBe(group.reason);
      }
    }
    expect(groups.flatMap((group) => group.tasks)).toHaveLength(nonCompletable.length);
    expect(nonCompletable.map((t) => t.id)).toEqual([1, 2, 3, 5, 6, 7]);
  });

  it("у доступных заданий нет ни одной группы", () => {
    expect(groupTasksByBlockReason([readyWithRaw])).toEqual([]);
  });
});
