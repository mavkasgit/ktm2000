import { describe, expect, it } from "vitest";
import type { SectionBoardTask } from "@/shared/api/shopfloor";
import {
  getCompletionBlockReason,
  getNonCompletableTasks,
  getReadyStatusLabel,
  getStatusColor,
  getStatusLabel,
  getTaskViewCategory,
  isTaskCompletable,
  isTaskFullyTransferred,
  groupTasksByBlockReason,
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

describe("getStatusLabel", () => {
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
    expect(getStatusLabel(task)).toBe("Завершен");
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
    expect(getStatusLabel(transferred)).toBe("Передано");
    expect(getStatusLabel(makeTask({ status: "ready" }))).toBe("Не передано");
  });

  it("для остальных статусов использует карту лейблов", () => {
    expect(getStatusLabel(makeTask({ status: "in_progress" }))).toBe("В работе");
    expect(getStatusLabel(makeTask({ status: "completed" }))).toBe("Завершен");
    expect(getStatusLabel(makeTask({ status: "cancelled" }))).toBe("Отменен");
  });
});

describe("getStatusColor", () => {
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
    expect(getStatusColor(t)).toContain("blue");
  });

  it("ready + Не передано → серый", () => {
    expect(getStatusColor(makeTask({ status: "ready" }))).toContain("slate");
  });

  it("in_progress → янтарный", () => {
    expect(getStatusColor(makeTask({ status: "in_progress" }))).toContain("amber");
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
    expect(getTaskViewCategory(task)).toBe("active");
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

describe("getTaskViewCategory", () => {
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
    expect(getTaskViewCategory(task)).toBe("completed");
  });

  it("ready с остатком → active", () => {
    expect(getTaskViewCategory(makeTask({ status: "ready" }))).toBe("active");
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
    expect(getTaskViewCategory(task)).toBe("completed");
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
    expect(getTaskViewCategory(task)).toBe("active");
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
    expect(getTaskViewCategory(makeTask({ status: "waiting_previous" }))).toBe("waiting");
  });
});

describe("getNonCompletableTasks", () => {
  it("оставляет только задачи, которые нельзя завершить", () => {
    const t1 = makeTask({ id: 1, status: "ready" });
    const t2 = makeTask({
      id: 2,
      status: "ready",
      previous_stage: {
        section_plan_line_id: 1,
        completed_quantity: "0",
        transferred_quantity: "10",
        received_quantity: "10",
      },
    });
    const t3 = makeTask({ id: 3, status: "completed" });
    const t4 = makeTask({ id: 4, status: "waiting_previous" });

    const result = getNonCompletableTasks([t1, t2, t3, t4]);
    expect(result.map((t) => t.id).sort()).toEqual([1, 3, 4]);
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
 * Баннер панели массовых операций собирает незавершаемые задания по кодам.
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
    const nonCompletable = getNonCompletableTasks(tasks);
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
