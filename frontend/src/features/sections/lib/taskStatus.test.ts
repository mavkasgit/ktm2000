import { describe, expect, it } from "vitest";
import type { SectionBoardTask } from "@/shared/api/shopfloor";
import {
  getReadyStatusLabel,
  getStatusLabel,
  getStatusColor,
  isTaskCompletable,
  getNonCompletableTasks,
  isTaskFullyTransferred,
  getTaskViewCategory,
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
