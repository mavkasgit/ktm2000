import { describe, expect, it } from "vitest";
import type { SectionBoardTask } from "@/shared/api/shopfloor";
import {
  getStatusDotClass,
  getTaskGroupHeaderState,
  getTaskOutputsProgressText,
  getTaskTone,
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

describe("getTaskTone", () => {
  it("различает ожидание, работу, взято в работу и завершение", () => {
    expect(getTaskTone(makeTask({ status: "waiting_previous" }))).toBe("waiting");
    expect(getTaskTone(makeTask({ status: "in_progress" }))).toBe("activeRunning");
    expect(getTaskTone(makeTask({ status: "ready" }))).toBe("active");
    expect(getTaskTone(makeTask({ status: "completed" }))).toBe("completed");
  });

  it("считает полностью переданное задание завершённым", () => {
    const task = makeTask({
      status: "ready",
      cache: cache({ transferred_quantity: "100", remaining_quantity: "0" }),
    });
    expect(getTaskTone(task)).toBe("completed");
  });

  it("не считает завершённой трансформацию с нулевым остатком выхода", () => {
    const task = makeTask({
      status: "ready",
      transforms_dimensions: true,
      cache: cache({ transferred_quantity: "100", remaining_quantity: "0" }),
    });
    expect(getTaskTone(task)).toBe("active");
  });
});

describe("getStatusDotClass", () => {
  it("красит полностью переданное задание как завершённое — копии точек разошлись", () => {
    const task = makeTask({
      status: "ready",
      cache: cache({ transferred_quantity: "100", remaining_quantity: "0" }),
    });
    expect(getStatusDotClass(task)).toBe("bg-emerald-500");
  });

  it("различает статусы работы, готовности, блокировки и ожидания", () => {
    expect(getStatusDotClass(makeTask({ status: "in_progress" }))).toBe("bg-amber-500 animate-pulse");
    expect(getStatusDotClass(makeTask({ status: "ready" }))).toBe("bg-slate-400");
    expect(getStatusDotClass(makeTask({ status: "blocked" }))).toBe("bg-red-500");
    expect(getStatusDotClass(makeTask({ status: "waiting_previous" }))).toBe("bg-yellow-400");
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
    expect(getStatusDotClass(task)).toBe("bg-blue-500");
  });
});

describe("getTaskGroupHeaderState", () => {
  it("в обычном режиме группа сворачивается, завершение группы доступно", () => {
    const group = { tasks: [completableTask(), completableTask({ id: 2 })] };
    const state = getTaskGroupHeaderState(group, {
      isCollapsed: true,
      isBulkMode: false,
      allSelected: false,
    });
    expect(state).toMatchObject({
      isCollapsed: true,
      canCollapse: true,
      collapseTitle: "Раскрыть",
      allSelected: false,
      hasCompletable: true,
      completeReason: null,
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

  it("называет причину, когда завершать нечего", () => {
    const state = getTaskGroupHeaderState(
      { tasks: [makeTask({ status: "completed" })] },
      { isCollapsed: false, isBulkMode: false, allSelected: false },
    );
    expect(state.hasCompletable).toBe(false);
    expect(state.completeReason).toBe("group_nothing_to_complete");
  });
});

describe("getTaskOutputsProgressText", () => {
  it("не выдаёт прогресс там, где выходов нет", () => {
    expect(getTaskOutputsProgressText(makeTask())).toBeNull();
    expect(getTaskOutputsProgressText(makeTask({ transforms_dimensions: true, outputs_progress: [] }))).toBeNull();
  });

  it("собирает прогресс по выходам одной строкой (ADR-0002)", () => {
    const task = makeTask({
      transforms_dimensions: true,
      outputs_progress: [
        { dimensions: { length_mm: 1800 }, quantity: "10", produced_quantity: "4" },
        { dimensions: { length_mm: 900 }, quantity: "10", produced_quantity: "10" },
      ],
    });
    expect(getTaskOutputsProgressText(task)).toBe("1,8 м: 4/10 · 0,9 м: 10/10");
  });
});
