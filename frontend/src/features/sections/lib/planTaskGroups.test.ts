import { describe, expect, it } from "vitest";
import type { SectionBoardTask } from "@/shared/api/shopfloor";
import { buildPlanTaskGroups } from "./planTaskGroups";

function makeTask(overrides: Partial<SectionBoardTask> = {}): SectionBoardTask {
  return {
    id: 1,
    product_id: 1,
    product_sku: "ЮП-2083",
    section_plan_line_id: 1,
    plan_position_id: 1,
    route_step_id: 1,
    sequence: 1,
    operation_code: "ANOD_01",
    operation_name: "Анодирование",
    is_significant: true,
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
    input_sku: "ЮП-2083",
    output_sku: "ЮП-2083",
    display_sku: "ЮП-2083",
    route_history: [],
    route_history_after: [],
    route_history_full: [],
    route_history_after_full: [],
    operation_codes: ["ANOD_01", "PACK_STRETCH"],
    operation_names: ["Анодирование", "Упаковка"],
    dimensions: { length_mm: 2750 },
    transforms_dimensions: false,
    input_dimensions: null,
    ...overrides,
  };
}

describe("buildPlanTaskGroups", () => {
  it("группирует по артикулу и размеру, игнорируя цвет анодирования", () => {
    const tasks = [
      makeTask({ id: 1, product_sku: "ЮП-2083", source_payload: { color: "silver" } }),
      makeTask({ id: 2, product_sku: "ЮП-2083", source_payload: { color: "black" } }),
      makeTask({
        id: 3,
        product_sku: "ЮП-2083",
        source_payload: { color: "silver" },
        dimensions: { length_mm: 3000 },
      }),
    ];

    const groups = buildPlanTaskGroups(tasks, "article");

    expect(groups).toHaveLength(2);
    const groupsByLabel = Object.fromEntries(groups.map((group) => [group.label, group]));
    expect(groupsByLabel["ЮП-2083 · 2,75 м"].rows.map((row) => row.task.id)).toEqual([1, 2]);
    expect(groupsByLabel["ЮП-2083 · 3 м"].rows.map((row) => row.task.id)).toEqual([3]);
  });

  it("объединяет разные артикулы одинакового цвета и размера", () => {
    const tasks = [
      makeTask({ id: 1, product_sku: "ЮП-2083", source_payload: { color: "silver" } }),
      makeTask({ id: 2, product_sku: "ЮП-2091", source_payload: { color: "silver" } }),
      makeTask({ id: 3, product_sku: "ЮП-2122", source_payload: { color: "black" } }),
    ];

    const groups = buildPlanTaskGroups(tasks, "anodizingColor");

    expect(groups).toHaveLength(2);
    const groupsByLabel = Object.fromEntries(groups.map((group) => [group.label, group]));
    expect(Object.keys(groupsByLabel).sort()).toEqual([
      "серебро · 2,75 м",
      "чёрный · 2,75 м",
    ]);
    expect(groupsByLabel["серебро · 2,75 м"].rows.map((row) => row.task.product_sku)).toEqual([
      "ЮП-2083",
      "ЮП-2091",
    ]);
    expect(groupsByLabel["чёрный · 2,75 м"].rows.map((row) => row.task.product_sku)).toEqual([
      "ЮП-2122",
    ]);
  });

  it("хранит упаковку и её детали в соответствующей строке задания", () => {
    const tasks = [
      makeTask({
        id: 1,
        source_payload: {
          packaging: "Стрейч",
          packaging_1_8_quantity: "80",
          add_quantity: "20",
        },
      }),
      makeTask({
        id: 2,
        source_payload: {
          packaging: "Короб",
          packaging_1_8_quantity: "40",
          add_quantity: "10",
        },
      }),
    ];

    const groups = buildPlanTaskGroups(tasks, "article");

    expect(groups).toHaveLength(1);
    expect(groups[0].rows.map((row) => ({
      taskId: row.task.id,
      packaging: row.packaging,
      details: row.packagingDetails,
    }))).toEqual([
      { taskId: 1, packaging: "Стрейч", details: ["1,8 м: 80", "Добавить: 20"] },
      { taskId: 2, packaging: "Короб", details: ["1,8 м: 40", "Добавить: 10"] },
    ]);
  });

  it("не объединяет одинаковый цвет с разными размерами", () => {
    const tasks = [
      makeTask({ id: 1, source_payload: { color: "silver" }, dimensions: { length_mm: 2750 } }),
      makeTask({ id: 2, source_payload: { color: "silver" }, dimensions: { length_mm: 3000 } }),
    ];

    const groups = buildPlanTaskGroups(tasks, "anodizingColor");
    expect(groups).toHaveLength(2);

    const groupsByLabel = Object.fromEntries(groups.map((group) => [group.label, group]));

    expect(Object.entries(groupsByLabel).map(([label, group]) => ({
      label,
      taskIds: group.rows.map((row) => row.task.id),
    }))).toEqual(expect.arrayContaining([
      { label: "серебро · 3 м", taskIds: [2] },
      { label: "серебро · 2,75 м", taskIds: [1] },
    ]));
  });
});
