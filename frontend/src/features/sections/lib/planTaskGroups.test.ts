import { describe, expect, it } from "vitest";
import type { SectionBoardTask } from "@/shared/api/shopfloor";
import { buildPlanTaskGroups } from "./planTaskGroups";
import {
  packagingBreakdown,
  packagingBreakdownLabel,
  taskOperations,
  taskPackaging,
} from "./taskView";

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
      makeTask({ id: 1, product_sku: "ЮП-2083", source_payload: { color: "серебро" } }),
      makeTask({ id: 2, product_sku: "ЮП-2083", source_payload: { color: "черный" } }),
      makeTask({
        id: 3,
        product_sku: "ЮП-2083",
        source_payload: { color: "серебро" },
        dimensions: { length_mm: 3000 },
      }),
    ];

    const groups = buildPlanTaskGroups(tasks, "article");

    expect(groups).toHaveLength(2);
    const groupsByLabel = Object.fromEntries(groups.map((group) => [group.label, group]));
    expect(groupsByLabel["ЮП-2083 · 2,75 м"].rows.map((row) => row.tasks.map((task) => task.id))).toEqual([[1], [2]]);
    expect(groupsByLabel["ЮП-2083 · 3 м"].rows.map((row) => row.tasks.map((task) => task.id))).toEqual([[3]]);
  });

  it("объединяет разные артикулы одинакового цвета и размера", () => {
    const tasks = [
      makeTask({ id: 1, product_sku: "ЮП-2083", source_payload: { color: "серебро" } }),
      makeTask({ id: 2, product_sku: "ЮП-2091", source_payload: { color: "серебро" } }),
      makeTask({ id: 3, product_sku: "ЮП-2122", source_payload: { color: "черный" } }),
    ];

    const groups = buildPlanTaskGroups(tasks, "anodizingColor");

    expect(groups).toHaveLength(2);
    const groupsByLabel = Object.fromEntries(groups.map((group) => [group.label, group]));
    expect(Object.keys(groupsByLabel).sort()).toEqual([
      "серебро · 2,75 м",
      "черный · 2,75 м",
    ]);
    expect(groupsByLabel["серебро · 2,75 м"].rows.map((row) => row.productSku)).toEqual([
      "ЮП-2083",
      "ЮП-2091",
    ]);
    expect(groupsByLabel["черный · 2,75 м"].rows.map((row) => row.productSku)).toEqual([
      "ЮП-2122",
    ]);
  });

  it("сливает задания с одинаковыми операциями и разбивает упаковку по количеству", () => {
    const tasks = [
      makeTask({
        id: 1,
        planned_quantity: "300",
        operation_codes: ["ANOD_01", "PACK_SPUNBOND"],
        operation_names: ["Серебро", "Спанбонд"],
        source_payload: { packaging: "смотка спанбондом поштучно в пачке 10 штук" },
      }),
      makeTask({
        id: 2,
        planned_quantity: "200",
        operation_codes: ["ANOD_01", "PACK_STRETCH"],
        operation_names: ["Серебро", "Стрейч"],
        source_payload: { packaging: "поф, красная этикетка РП 23*150" },
      }),
    ];

    const groups = buildPlanTaskGroups(tasks, "article");

    expect(groups).toHaveLength(1);
    expect(groups[0].rows).toHaveLength(1);
    const row = groups[0].rows[0];
    expect(row.tasks.map((task) => task.id)).toEqual([1, 2]);
    expect(row.planQty).toBe(500);
    expect(row.balanceQty).toBe(500);
    expect(row.packaging).toEqual([
      { label: "Спанбонд", qty: 300 },
      { label: "Стрейч", qty: 200 },
    ]);
    expect(groups[0].totalQtyPlan).toBe(500);
  });

  it("не сливает задания с разными операциями участка", () => {
    const tasks = [
      makeTask({ id: 1, operation_code: "ANOD_01", operation_name: "Серебро" }),
      makeTask({ id: 2, operation_code: "ANOD_05", operation_name: "Чёрный" }),
    ];

    const groups = buildPlanTaskGroups(tasks, "article");

    expect(groups[0].rows.map((row) => row.operationName)).toEqual(["Серебро", "Чёрный"]);
  });

  it("оставляет упаковку пустой, если на участке нет упаковочной операции", () => {
    const groups = buildPlanTaskGroups(
      [makeTask({ operation_codes: ["ANOD_01"], operation_names: ["Серебро"] })],
      "article",
    );

    expect(groups[0].rows[0].packaging).toEqual([]);
  });

  it("не объединяет одинаковый цвет с разными размерами", () => {
    const tasks = [
      makeTask({ id: 1, source_payload: { color: "серебро" }, dimensions: { length_mm: 2750 } }),
      makeTask({ id: 2, source_payload: { color: "серебро" }, dimensions: { length_mm: 3000 } }),
    ];

    const groups = buildPlanTaskGroups(tasks, "anodizingColor");
    expect(groups).toHaveLength(2);

    const groupsByLabel = Object.fromEntries(groups.map((group) => [group.label, group]));

    expect(Object.entries(groupsByLabel).map(([label, group]) => ({
      label,
      taskIds: group.rows.map((row) => row.tasks.map((task) => task.id)),
    }))).toEqual(expect.arrayContaining([
      { label: "серебро · 3 м", taskIds: [[2]] },
      { label: "серебро · 2,75 м", taskIds: [[1]] },
    ]));
  });
});

describe("колонки «Операция» и «Упаковка» доски", () => {
  it("показывает в «Операции» операции участка, а упаковку — отдельно", () => {
    const task = makeTask({
      operation_code: "ANOD_05",
      operation_name: "Чёрный",
      operation_codes: ["ANOD_05", "PACK_SPUNBOND"],
      operation_names: ["Чёрный", "Спанбонд"],
    });

    // Упаковочная операция в список «Операции» не входит: её несёт своя колонка.
    expect(taskOperations(task)).toEqual(["Чёрный"]);
    expect(taskPackaging(task)).toBe("Спанбонд");
  });

  it("перечисляет несколько операций участка по порядку", () => {
    const task = makeTask({
      operation_code: "PRESS_WINDOW",
      operation_name: "Окно",
      operation_codes: ["PRESS_WINDOW", "PRESS_COMB", "PACK_STRETCH"],
      operation_names: ["Окно", "Гребенка", "Стрейч"],
    });

    expect(taskOperations(task)).toEqual(["Окно", "Гребенка"]);
  });

  it("разбивает упаковку слитой строки по видам с количеством", () => {
    const tasks = [
      makeTask({
        id: 1,
        planned_quantity: "300",
        operation_codes: ["ANOD_01", "PACK_SPUNBOND"],
        operation_names: ["Серебро", "Спанбонд"],
      }),
      makeTask({
        id: 2,
        planned_quantity: "200",
        operation_codes: ["ANOD_01", "PACK_STRETCH"],
        operation_names: ["Серебро", "Стрейч"],
      }),
      makeTask({
        id: 3,
        planned_quantity: "50",
        operation_codes: ["ANOD_01", "PACK_STRETCH"],
        operation_names: ["Серебро", "Стрейч"],
      }),
    ];

    expect(packagingBreakdown(tasks)).toEqual([
      { label: "Спанбонд", qty: 300 },
      { label: "Стрейч", qty: 250 },
    ]);
    expect(packagingBreakdownLabel(tasks, (value) => String(value))).toBe(
      "Спанбонд 300 · Стрейч 250",
    );
  });

  it("один вид упаковки подписывается без количества", () => {
    const tasks = [
      makeTask({ operation_codes: ["ANOD_05", "PACK_STRETCH"], operation_names: ["Чёрный", "Стрейч"] }),
    ];

    expect(packagingBreakdownLabel(tasks, (value) => String(value))).toBe("Стрейч");
  });

  it("участок без упаковочной операции показывает прочерк", () => {
    const tasks = [makeTask({ operation_codes: ["SAW"], operation_names: ["Резка на пиле"] })];

    expect(packagingBreakdownLabel(tasks, (value) => String(value))).toBe("—");
  });
});
