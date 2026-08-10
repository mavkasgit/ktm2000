import { describe, expect, it } from "vitest";
import type { SectionBoardTask, TaskGroup } from "@/shared/api/shopfloor";
import { buildPlanRows, type PlanRow } from "./planTableRows";
import { PRESET_PROFILES, type GroupingProfile } from "./groupingProfiles";
import { groupTasksByProfile } from "./groupTasksByProfile";

const SKU_PROFILE = PRESET_PROFILES.find((p) => p.id === "sku")!;

function makeTask(overrides: Partial<SectionBoardTask> = {}): SectionBoardTask {
  return {
    id: 1,
    product_id: 1,
    product_sku: "ЮП-460",
    section_plan_line_id: 1,
    plan_position_id: 1,
    route_step_id: 1,
    sequence: 1,
    operation_code: null,
    operation_name: "Резка",
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
    input_sku: "ЮП-460",
    output_sku: "ЮП-460",
    display_sku: "ЮП-460",
    route_history: [],
    route_history_after: [],
    route_history_full: [],
    route_history_after_full: [],
    operation_codes: [null],
    operation_names: ["Резка"],
    dimensions: null,
    transforms_dimensions: false,
    input_dimensions: null,
    ...overrides,
  };
}

function groupTasks(tasks: SectionBoardTask[], profile: GroupingProfile = SKU_PROFILE): TaskGroup[] {
  return groupTasksByProfile(tasks, profile);
}

function qty(row: PlanRow): { plan: number; done: number; transferred: number; balance: number } {
  return {
    plan: row.planQty,
    done: row.doneQty,
    transferred: row.transferredQty,
    balance: row.balanceQty,
  };
}

// ---------------------------------------------------------------------------
// «Выдача» — одна строка на группу по входу
// ---------------------------------------------------------------------------

describe("buildPlanRows (выдача)", () => {
  it("обычный этап — одна строка на группу, план = сумма задач", () => {
    const tasks = [
      makeTask({ id: 1, planned_quantity: "100" }),
      makeTask({ id: 2, planned_quantity: "50" }),
    ];
    const rows = buildPlanRows(groupTasks(tasks), "issue");
    expect(rows).toHaveLength(1);
    expect(rows[0].planQty).toBe(150);
    expect(rows[0].ordersCount).toBe(2);
  });

  it("резка (трансформация) — строка по входу, кол-во = план группы", () => {
    const task = makeTask({
      transforms_dimensions: true,
      input_dimensions: { length_mm: 3000 },
      planned_quantity: "150",
      outputs: [
        { row_number: 1, quantity: "150", dimensions: { length_mm: 900 } },
        { row_number: 2, quantity: "150", dimensions: { length_mm: 1800 } },
      ],
      outputs_progress: [
        { row_number: 1, quantity: "150", produced_quantity: "150", transferred_quantity: "150" },
        { row_number: 2, quantity: "150", produced_quantity: "150", transferred_quantity: "0" },
      ],
    });
    const rows = buildPlanRows(groupTasks([task]), "issue");
    expect(rows).toHaveLength(1);
    expect(rows[0].dimensions).toEqual({ length_mm: 3000 });
    expect(qty(rows[0])).toEqual({ plan: 150, done: 0, transferred: 0, balance: 150 });
  });
});

// ---------------------------------------------------------------------------
// «Сдача» — разбивка по выходам
// ---------------------------------------------------------------------------

describe("buildPlanRows (сдача)", () => {
  it("резка — строка на каждый выход со своим размером и количеством", () => {
    const task = makeTask({
      transforms_dimensions: true,
      input_dimensions: { length_mm: 3000 },
      planned_quantity: "150",
      outputs: [
        { row_number: 1, quantity: "150", dimensions: { length_mm: 900 } },
        { row_number: 2, quantity: "150", dimensions: { length_mm: 1800 } },
      ],
      outputs_progress: [
        { row_number: 1, quantity: "150", produced_quantity: "100", transferred_quantity: "80" },
        { row_number: 2, quantity: "150", produced_quantity: "150", transferred_quantity: "150" },
      ],
    });
    const rows = buildPlanRows(groupTasks([task]), "handover");
    expect(rows).toHaveLength(2);
    expect(rows[0].dimensions).toEqual({ length_mm: 900 });
    expect(qty(rows[0])).toEqual({ plan: 150, done: 100, transferred: 80, balance: 50 });
    expect(rows[1].dimensions).toEqual({ length_mm: 1800 });
    expect(qty(rows[1])).toEqual({ plan: 150, done: 150, transferred: 150, balance: 0 });
  });

  it("выходы без прогресса — Сделано/Передано = 0", () => {
    const task = makeTask({
      transforms_dimensions: true,
      input_dimensions: { length_mm: 3000 },
      planned_quantity: "150",
      outputs: [
        { row_number: 1, quantity: "150", dimensions: { length_mm: 900 } },
        { row_number: 2, quantity: "150", dimensions: { length_mm: 1800 } },
      ],
      outputs_progress: [],
    });
    const rows = buildPlanRows(groupTasks([task]), "handover");
    expect(rows).toHaveLength(2);
    expect(qty(rows[0])).toEqual({ plan: 150, done: 0, transferred: 0, balance: 150 });
    expect(qty(rows[1])).toEqual({ plan: 150, done: 0, transferred: 0, balance: 150 });
  });

  it("нетрансформирующее задание — одна строка (само задание)", () => {
    const task = makeTask({
      dimensions: { length_mm: 2700 },
      planned_quantity: "100",
      cache: {
        ...makeTask().cache,
        completed_quantity: "40",
        transferred_quantity: "30",
      },
    });
    const rows = buildPlanRows(groupTasks([task]), "handover");
    expect(rows).toHaveLength(1);
    expect(rows[0].dimensions).toEqual({ length_mm: 2700 });
    expect(qty(rows[0])).toEqual({ plan: 100, done: 40, transferred: 30, balance: 60 });
  });

  it("«Заказов» сдачи = число заданий, давших выход (факт по ним оприходован)", () => {
    const done = makeTask({
      id: 1,
      transforms_dimensions: true,
      input_dimensions: { length_mm: 3000 },
      planned_quantity: "150",
      outputs: [{ row_number: 1, quantity: "150", dimensions: { length_mm: 900 } }],
      outputs_progress: [
        { row_number: 1, quantity: "150", produced_quantity: "150", transferred_quantity: "150" },
      ],
    });
    const pending = makeTask({
      id: 2,
      transforms_dimensions: true,
      input_dimensions: { length_mm: 3000 },
      planned_quantity: "150",
      outputs: [{ row_number: 1, quantity: "150", dimensions: { length_mm: 900 } }],
      outputs_progress: [],
      status: "pending",
    });
    const rows = buildPlanRows(groupTasks([done, pending]), "handover");
    // Обе строки на экране (план−сделано > 0), но выход дало только завершённое.
    expect(rows).toHaveLength(2);
    expect(rows[0].ordersCount).toBe(1);
  });

  it("«Заказов» сдачи считает все завершённые задания группы", () => {
    const a = makeTask({
      id: 1,
      transforms_dimensions: true,
      input_dimensions: { length_mm: 3000 },
      planned_quantity: "100",
      outputs: [{ row_number: 1, quantity: "100", dimensions: { length_mm: 900 } }],
      outputs_progress: [
        { row_number: 1, quantity: "100", produced_quantity: "60", transferred_quantity: "60" },
      ],
    });
    const b = makeTask({
      id: 2,
      transforms_dimensions: true,
      input_dimensions: { length_mm: 3000 },
      planned_quantity: "100",
      outputs: [{ row_number: 1, quantity: "100", dimensions: { length_mm: 900 } }],
      outputs_progress: [
        { row_number: 1, quantity: "100", produced_quantity: "100", transferred_quantity: "100" },
      ],
    });
    const rows = buildPlanRows(groupTasks([a, b]), "handover");
    expect(rows).toHaveLength(2);
    expect(rows[0].ordersCount).toBe(2);
  });

  it("строка несёт ключ группы для скрытия", () => {
    const task = makeTask({ id: 1, planned_quantity: "100" });
    const groups = groupTasks([task]);
    const rows = buildPlanRows(groups, "issue");
    expect(rows[0].groupKey).toBe(groups[0].key);
  });
});
