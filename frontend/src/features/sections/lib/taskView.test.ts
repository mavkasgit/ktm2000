import { describe, expect, it } from "vitest";
import type { SectionBoardTask } from "@/shared/api/shopfloor";
import { getTaskRowState } from "./taskStatus";
import {
  getTaskGroupHeaderState,
} from "./taskView";

function cache(overrides: Partial<SectionBoardTask["cache"]> = {}) {
  return {
    available_quantity: "0",
    issued_quantity: "0",
    completed_quantity: "0",
    transferred_quantity: "0",
    received_quantity: "0",
    rejected_quantity: "0",
    remaining_quantity: "100",
    ...overrides,
  };
}

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
    cache: cache(),
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

/** Задание с выданным сырьём: его можно завершить. */
function completableTask(overrides: Partial<SectionBoardTask> = {}): SectionBoardTask {
  return makeTask({
    status: "in_progress",
    previous_stage: {
      section_plan_line_id: 1,
      completed_quantity: "100",
      transferred_quantity: "100",
      received_quantity: "0",
    },
    cache: cache({ issued_quantity: "100", remaining_quantity: "0" }),
    ...overrides,
  });
}

describe("getTaskRowState: тон", () => {
  it("различает ожидание, работу, взято в работу и завершение", () => {
    expect(getTaskRowState(makeTask({ status: "waiting_previous" })).tone).toBe("waiting");
    expect(getTaskRowState(makeTask({ status: "in_progress" })).tone).toBe("activeRunning");
    expect(getTaskRowState(makeTask({ status: "ready" })).tone).toBe("active");
    expect(getTaskRowState(makeTask({ status: "completed" })).tone).toBe("completed");
  });

  it("считает полностью переданное задание завершённым", () => {
    const task = makeTask({
      status: "ready",
      cache: cache({ transferred_quantity: "100", remaining_quantity: "0" }),
    });
    expect(getTaskRowState(task).tone).toBe("completed");
  });

  it("не считает завершённой трансформацию с нулевым остатком выхода", () => {
    const task = makeTask({
      status: "ready",
      transforms_dimensions: true,
      cache: cache({ transferred_quantity: "100", remaining_quantity: "0" }),
    });
    expect(getTaskRowState(task).tone).toBe("active");
  });
});

describe("getTaskRowState: цвет точки", () => {
  it("красит полностью переданное задание как завершённое — копии точек разошлись", () => {
    const task = makeTask({
      status: "ready",
      cache: cache({ transferred_quantity: "100", remaining_quantity: "0" }),
    });
    expect(getTaskRowState(task).dotClass).toBe("bg-emerald-500");
  });

  it("различает статусы работы, готовности, блокировки и ожидания", () => {
    expect(getTaskRowState(makeTask({ status: "in_progress" })).dotClass).toBe("bg-amber-500 animate-pulse");
    expect(getTaskRowState(makeTask({ status: "ready" })).dotClass).toBe("bg-slate-400");
    expect(getTaskRowState(makeTask({ status: "blocked" })).dotClass).toBe("bg-red-500");
    expect(getTaskRowState(makeTask({ status: "waiting_previous" })).dotClass).toBe("bg-yellow-400");
  });

  it("красит готовое задание с переданным входом в синий, а не в серый", () => {
    const task = makeTask({
      status: "ready",
      previous_stage: {
        section_plan_line_id: 1,
        completed_quantity: "100",
        transferred_quantity: "100",
        received_quantity: "0",
      },
    });
    expect(getTaskRowState(task).dotClass).toBe("bg-blue-500");
  });
});

describe("getTaskGroupHeaderState", () => {
  it("в обычном режиме группа сворачивается", () => {
    const group = { tasks: [completableTask(), completableTask({ id: 2 })] };
    const state = getTaskGroupHeaderState(group, {
      isCollapsed: true,
      isBulkMode: false,
      allSelected: false,
    });
    expect(state).toEqual({
      isCollapsed: true,
      canCollapse: true,
      collapseTitle: "Раскрыть",
      allSelected: false,
    });
  });

  it("в массовом режиме группа не сворачивается", () => {
    const state = getTaskGroupHeaderState(
      { tasks: [completableTask()] },
      { isCollapsed: false, isBulkMode: true, allSelected: true },
    );
    expect(state.canCollapse).toBe(false);
    expect(state.allSelected).toBe(true);
  });
});
