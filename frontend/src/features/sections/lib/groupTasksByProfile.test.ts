import { describe, expect, it } from "vitest";
import type { SectionBoardTask } from "@/shared/api/shopfloor";
import {
  groupTasksByProfile,
  sortGroupsByRemaining,
  taskGroupingDimensions,
  taskGroupingDimensionsKey,
} from "./groupTasksByProfile";
import { PRESET_PROFILES, type GroupingProfile } from "./groupingProfiles";

const SKU_PROFILE = PRESET_PROFILES.find((p) => p.id === "sku")!;
const ROUTE_PROFILE = PRESET_PROFILES.find((p) => p.id === "sku+routeHistory")!;

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
    input_sku: "ЮП-460",
    output_sku: "ЮП-460",
    display_sku: "ЮП-460",
    route_history: [],
    route_history_after: [],
    route_history_full: [],
    route_history_after_full: [],
    operation_codes: [null],
    operation_names: ["Операция"],
    dimensions: null,
    transforms_dimensions: false,
    input_dimensions: null,
    ...overrides,
  };
}

// ---------------------------------------------------------------------------
// taskGroupingDimensions
// ---------------------------------------------------------------------------

describe("taskGroupingDimensions", () => {
  it("обычный этап — берёт габарит задания (dimensions)", () => {
    const task = makeTask({ dimensions: { length_mm: 2700 } });
    expect(taskGroupingDimensions(task)).toEqual({ length_mm: 2700 });
  });

  it("резка не меняет домен размера: берётся габарит задания", () => {
    const task = makeTask({
      transforms_dimensions: true,
      dimensions: { length_mm: 2700 },
      input_dimensions: { length_mm: 3000 },
    });
    expect(taskGroupingDimensions(task)).toEqual({ length_mm: 2700 });
  });

  it("безразмерные — null", () => {
    const task = makeTask({ dimensions: null });
    expect(taskGroupingDimensions(task)).toBeNull();
  });
});

describe("taskGroupingDimensionsKey", () => {
  it("разные размеры дают разные ключи", () => {
    const a = taskGroupingDimensionsKey(makeTask({ dimensions: { length_mm: 2700 } }));
    const b = taskGroupingDimensionsKey(makeTask({ dimensions: { length_mm: 3000 } }));
    const none = taskGroupingDimensionsKey(makeTask({ dimensions: null }));
    expect(a).not.toBe(b);
    expect(a).not.toBe(none);
  });

  it("безразмерные и пустой объект — один маркер", () => {
    const none = taskGroupingDimensionsKey(makeTask({ dimensions: null }));
    const empty = taskGroupingDimensionsKey(makeTask({ dimensions: {} }));
    expect(none).toBe(empty);
  });
});

// ---------------------------------------------------------------------------
// groupTasksByProfile — размер как принудительный критерий
// ---------------------------------------------------------------------------

describe("groupTasksByProfile", () => {
  it("разные размеры одного артикула — разные группы, порядок входа сохраняется", () => {
    const tasks = [
      makeTask({ id: 1, dimensions: { length_mm: 2700 } }),
      makeTask({ id: 2, dimensions: { length_mm: 3000 } }),
    ];
    const groups = groupTasksByProfile(tasks, SKU_PROFILE);
    expect(groups).toHaveLength(2);
    // Порядок строк — дело вызывающего: группировка не пересортировывает,
    // иначе она затирала бы сортировку колонки, выбранную пользователем.
    expect(groups[0].label).toBe("ЮП-460 · 2,7 м");
    expect(groups[1].label).toBe("ЮП-460 · 3 м");
  });

  it("группировка не затирает сортировку по колонке: серверный порядок доходит до групп", () => {
    // Сортировка по количеству убыв. — обратная порядку размеров.
    const tasks = [
      makeTask({ id: 1, dimensions: { length_mm: 3000 }, planned_quantity: "10" }),
      makeTask({ id: 2, dimensions: { length_mm: 2700 }, planned_quantity: "900" }),
    ];
    const groups = groupTasksByProfile(tasks, SKU_PROFILE);
    expect(groups.map((g) => g.label)).toEqual(["ЮП-460 · 3 м", "ЮП-460 · 2,7 м"]);
  });

  it("безразмерные — отдельная строка «артикул · —»", () => {
    const tasks = [
      makeTask({ id: 1, dimensions: { length_mm: 2700 } }),
      makeTask({ id: 2, dimensions: null }),
    ];
    const groups = groupTasksByProfile(tasks, SKU_PROFILE);
    expect(groups).toHaveLength(2);
    const byLabel = Object.fromEntries(groups.map((g) => [g.label, g]));
    expect(byLabel["ЮП-460 · 2,7 м"]).toBeTruthy();
    expect(byLabel["ЮП-460 · —"]).toBeTruthy();
  });

  it("размер входит в ключ: разные размеры не смешиваются", () => {
    const tasks = [
      makeTask({ id: 1, dimensions: { length_mm: 2700 } }),
      makeTask({ id: 2, dimensions: { length_mm: 3000 } }),
    ];
    const groups = groupTasksByProfile(tasks, SKU_PROFILE);
    const keys = groups.map((g) => g.key).sort();
    expect(keys).toHaveLength(2);
    expect(keys[0]).toContain("length_mm=2700");
    expect(keys[1]).toContain("length_mm=3000");
  });

  it("резка группируется по габариту задания, а не по входу этапа (#286)", () => {
    const tasks = [
      makeTask({ id: 1, transforms_dimensions: true, dimensions: { length_mm: 2700 }, input_dimensions: { length_mm: 3000 } }),
      makeTask({ id: 2, transforms_dimensions: true, dimensions: { length_mm: 3000 }, input_dimensions: { length_mm: 2700 } }),
    ];
    const groups = groupTasksByProfile(tasks, SKU_PROFILE);
    expect(groups).toHaveLength(2);
    expect(groups[0].label).toBe("ЮП-460 · 2,7 м");
    expect(groups[1].label).toBe("ЮП-460 · 3 м");
  });

  it("пара (source_sku с «+») группируется как один артикул по размеру пересечения", () => {
    // У пары product_sku уже несёт source_sku с «+», а размер пересечения
    // компонентов бэкенд отдаёт в dimensions/input_dimensions.
    const tasks = [
      makeTask({ id: 1, product_sku: "ЮП-460+ЮП-461", dimensions: { length_mm: 2700 } }),
      makeTask({ id: 2, product_sku: "ЮП-460+ЮП-461", dimensions: { length_mm: 3000 } }),
      makeTask({ id: 3, product_sku: "ЮП-460+ЮП-461", dimensions: { length_mm: 2700 } }),
    ];
    const groups = groupTasksByProfile(tasks, SKU_PROFILE);
    expect(groups).toHaveLength(2);
    const byLabel = Object.fromEntries(groups.map((g) => [g.label, g]));
    expect(byLabel["ЮП-460+ЮП-461 · 2,7 м"].tasks).toHaveLength(2);
    expect(byLabel["ЮП-460+ЮП-461 · 3 м"].tasks).toHaveLength(1);
  });

  it("профиль «sku» фактически «артикул + размер»", () => {
    const tasks = [
      makeTask({ id: 1, dimensions: { length_mm: 2700 } }),
      makeTask({ id: 2, dimensions: { length_mm: 3000 } }),
    ];
    const groups = groupTasksByProfile(tasks, SKU_PROFILE);
    expect(groups).toHaveLength(2);
  });

  it("остальные критерии профиля продолжают разделять внутри размера", () => {
    const profile: GroupingProfile = {
      id: "custom",
      name: "Свой",
      criteria: ["customField"],
      customFields: ["batch"],
    };
    const tasks = [
      makeTask({ id: 1, dimensions: { length_mm: 2700 }, source_payload: { batch: "B1" } }),
      makeTask({ id: 2, dimensions: { length_mm: 2700 }, source_payload: { batch: "B2" } }),
    ];
    const groups = groupTasksByProfile(tasks, profile);
    expect(groups).toHaveLength(2);
    // ключ начинается с артикула и размера, дальше — кастомное поле
    expect(groups[0].key).toMatch(/^ЮП-460__length_mm=2700__B1/);
    expect(groups[1].key).toMatch(/^ЮП-460__length_mm=2700__B2/);
  });
});

// ---------------------------------------------------------------------------
// sortGroupsByRemaining
// ---------------------------------------------------------------------------

function taskWithRemaining(
  id: number,
  remaining: string,
  dimensions: Record<string, unknown> | null = null,
  sku = "ЮП-460",
): SectionBoardTask {
  const base = makeTask();
  return makeTask({
    id,
    product_sku: sku,
    dimensions,
    cache: { ...base.cache, remaining_quantity: remaining },
  });
}

describe("sortGroupsByRemaining", () => {
  it("по остатку убыв.; при равных — подпись группы по алфавиту", () => {
    const groups = [
      groupTasksByProfile([taskWithRemaining(1, "50", { length_mm: 3000 })], SKU_PROFILE)[0],
      groupTasksByProfile([taskWithRemaining(2, "200", { length_mm: 2700 })], SKU_PROFILE)[0],
      groupTasksByProfile([taskWithRemaining(3, "50", { length_mm: 1000 })], SKU_PROFILE)[0],
    ];
    const sorted = sortGroupsByRemaining(groups);
    expect(sorted.map((g) => g.label)).toEqual([
      "ЮП-460 · 2,7 м", // остаток 200 — первым
      "ЮП-460 · 1 м",   // равный остаток 50 — подпись по алфавиту
      "ЮП-460 · 3 м",
    ]);
  });

  it("при равном остатке — артикул по алфавиту", () => {
    const groups = [
      groupTasksByProfile([taskWithRemaining(1, "100", null, "ЯП-900")], SKU_PROFILE)[0],
      groupTasksByProfile([taskWithRemaining(2, "100", null, "АП-100")], SKU_PROFILE)[0],
    ];
    const sorted = sortGroupsByRemaining(groups);
    expect(sorted.map((g) => g.tasks[0].product_sku)).toEqual(["АП-100", "ЯП-900"]);
  });

  it("суммирует остаток заданий группы", () => {
    const group = groupTasksByProfile(
      [taskWithRemaining(1, "30"), taskWithRemaining(2, "20")],
      SKU_PROFILE,
    )[0];
    expect(group.totalRemaining).toBe(50);
  });
});
