import { describe, expect, it } from "vitest";

import type { SectionBoardTask } from "@/shared/api/shopfloor";
import { getCurrentSectionTasks, getDailyPlanCreationCandidates } from "./dailyPlans";

function makeTask(overrides: Partial<SectionBoardTask> = {}): SectionBoardTask {
  return {
    id: 1,
    product_id: 1,
    product_sku: "SKU-A",
    section_plan_line_id: 1,
    plan_position_id: 1,
    route_step_id: 1,
    sequence: 1,
    operation_code: "op",
    operation_name: "Операция",
    is_significant: true,
    planned_quantity: "10",
    status: "ready",
    cache: {
      available_quantity: "10",
      issued_quantity: "0",
      completed_quantity: "0",
      transferred_quantity: "0",
      received_quantity: "0",
      rejected_quantity: "0",
      remaining_quantity: "10",
    },
    previous_stage: null,
    next_task_id: null,
    next_task_status: null,
    next_operation_name: null,
    source_ref: null,
    source_payload: {},
    source_fingerprint: null,
    input_sku: "SKU-A",
    output_sku: "SKU-A",
    display_sku: "SKU-A",
    route_history: [],
    route_history_after: [],
    route_history_full: [],
    route_history_after_full: [],
    operation_codes: [],
    operation_names: [],
    ...overrides,
  };
}

/** Завершённое задание: терминальный статус плюс полный факт. */
function completedTask(id: number): SectionBoardTask {
  return makeTask({
    id,
    status: "completed",
    cache: {
      available_quantity: "0",
      issued_quantity: "10",
      completed_quantity: "10",
      transferred_quantity: "10",
      received_quantity: "10",
      rejected_quantity: "0",
      remaining_quantity: "0",
    },
  });
}

describe("getCurrentSectionTasks", () => {
  it("оставляет задание, занятое планом: просмотр — это картина участка, а не кандидаты", () => {
    const free = makeTask({ id: 1 });
    const taken = makeTask({ id: 2, in_daily_plan: true });

    const ids = getCurrentSectionTasks([free, taken]).map((task) => task.id);

    expect(ids).toEqual([1, 2]);
  });

  it("прячет завершённые — они видны только в составе выбранного плана", () => {
    const active = makeTask({ id: 1 });

    const ids = getCurrentSectionTasks([active, completedTask(2)]).map((task) => task.id);

    expect(ids).toEqual([1]);
  });
});
describe("getDailyPlanCreationCandidates", () => {
  it("прячет задание, уже включённое в дневной план", () => {
    const free = makeTask({ id: 1 });
    const taken = makeTask({ id: 2, in_daily_plan: true });

    const ids = getDailyPlanCreationCandidates([free, taken]).map((task) => task.id);

    expect(ids).toEqual([1]);
  });

  it("без признака `in_daily_plan` ведёт себя как прежде: режет только завершённые", () => {
    const active = makeTask({ id: 1 });
    const completed = makeTask({
      id: 2,
      status: "completed",
      cache: {
        available_quantity: "0",
        issued_quantity: "10",
        completed_quantity: "10",
        transferred_quantity: "10",
        received_quantity: "10",
        rejected_quantity: "0",
        remaining_quantity: "0",
      },
    });

    const ids = getDailyPlanCreationCandidates([active, completed]).map((task) => task.id);

    expect(ids).toEqual([1]);
  });

  it("признак `false` оставляет задание кандидатом", () => {
    const free = makeTask({ id: 1, in_daily_plan: false });
    const taken = makeTask({ id: 2, in_daily_plan: true });

    const ids = getDailyPlanCreationCandidates([free, taken]).map((task) => task.id);

    expect(ids).toEqual([1]);
  });
});