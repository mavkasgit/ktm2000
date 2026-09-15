import { describe, expect, it } from "vitest";
import type { ReadyToTransferTask } from "@/shared/api/transfers";
import {
  groupReadyTransfers,
  type ReadyTransferGroup,
  type ReadyTransferRowItem,
} from "./groupReadyTransfers";

function makeTask(overrides: Partial<ReadyToTransferTask> = {}): ReadyToTransferTask {
  return {
    task_id: 1,
    section_id: 1,
    section_code: "SAW",
    section_name: "Пила",
    plan_position_id: 1,
    route_stage_id: 131,
    sequence: 1,
    operation_code: null,
    operation_name: "Пила",
    product_id: 42,
    product_sku: "ЮП-2083",
    planned_quantity: "50",
    completed_quantity: "350",
    already_transferred_quantity: "0",
    transferable_quantity: "50",
    has_next_step: true,
    next_section_id: 4,
    next_section_code: "SHOT_BLAST",
    next_section_name: "Дробеструй",
    next_operation_name: "Дробеструй",
    next_step_sequence: 2,
    next_step_is_final: false,
    is_final: false,
    completion_comment: null,
    dimensions: { length_mm: 2750 },
    dimensions_label: "2,75 м",
    ...overrides,
  };
}

function groupsOf(items: ReadyTransferRowItem[]): ReadyTransferGroup[] {
  return items.filter((item): item is ReadyTransferGroup => item.kind === "group");
}

describe("groupReadyTransfers", () => {
  it("собирает строки одного артикула, участка, размера и адресата в одну группу, сохраняя порядок входа", () => {
    const items = groupReadyTransfers([
      makeTask({ task_id: 1, plan_position_id: 11 }),
      makeTask({ task_id: 2, plan_position_id: 12 }),
      makeTask({ task_id: 3, plan_position_id: 13 }),
    ]);

    expect(items).toHaveLength(1);
    const [group] = groupsOf(items);
    expect(group.rows.map((row) => row.task_id)).toEqual([1, 2, 3]);
    expect(group.productSku).toBe("ЮП-2083");
    expect(group.sectionId).toBe(1);
    expect(group.nextSectionId).toBe(4);
  });

  it("разделяет выходы раскроя разных размеров, снятые с одного участка", () => {
    const items = groupReadyTransfers([
      makeTask({ task_id: 1, dimensions: { length_mm: 900 }, dimensions_label: "0,9 м" }),
      makeTask({ task_id: 2, dimensions: { length_mm: 1350 }, dimensions_label: "1,35 м" }),
      makeTask({ task_id: 3, dimensions: { length_mm: 1800 }, dimensions_label: "1,8 м" }),
      makeTask({ task_id: 4, dimensions: { length_mm: 2700 }, dimensions_label: "2,7 м" }),
    ]);

    expect(items.map((item) => item.kind)).toEqual(["single", "single", "single", "single"]);
    expect(
      items.map((item) => (item.kind === "single" ? item.row.dimensions : null)),
    ).toEqual([{ length_mm: 900 }, { length_mm: 1350 }, { length_mm: 1800 }, { length_mm: 2700 }]);
  });

  it("разделяет один размер, уходящий разным адресатам (анод: склад ПФ против склада ГП)", () => {
    const items = groupReadyTransfers([
      makeTask({ task_id: 1, next_section_id: 4, next_section_code: "PF_STOCK" }),
      makeTask({ task_id: 2, next_section_id: 4, next_section_code: "PF_STOCK" }),
      makeTask({ task_id: 3, next_section_id: 7, next_section_code: "GP_STOCK" }),
      makeTask({ task_id: 4, next_section_id: 7, next_section_code: "GP_STOCK" }),
    ]);

    const groups = groupsOf(items);
    expect(groups).toHaveLength(2);
    expect(groups.map((group) => group.nextSectionId)).toEqual([4, 7]);
    expect(groups[0].rows.map((row) => row.task_id)).toEqual([1, 2]);
    expect(groups[1].rows.map((row) => row.task_id)).toEqual([3, 4]);
  });

  it("разделяет один артикул одного размера, лежащий на разных участках", () => {
    const items = groupReadyTransfers([
      makeTask({ task_id: 1, section_id: 1 }),
      makeTask({ task_id: 2, section_id: 1 }),
      makeTask({ task_id: 3, section_id: 5, section_code: "ANODE", section_name: "Анод" }),
      makeTask({ task_id: 4, section_id: 5, section_code: "ANODE", section_name: "Анод" }),
    ]);

    const groups = groupsOf(items);
    expect(groups).toHaveLength(2);
    expect(groups.map((group) => group.sectionId)).toEqual([1, 5]);
    expect(groups[0].rows.map((row) => row.task_id)).toEqual([1, 2]);
    expect(groups[1].rows.map((row) => row.task_id)).toEqual([3, 4]);
  });

  it("разделяет разные артикулы одного размера на одном участке", () => {
    const items = groupReadyTransfers([
      makeTask({ task_id: 1, product_sku: "ЮП-2083" }),
      makeTask({ task_id: 2, product_sku: "ЮП-2083" }),
      makeTask({ task_id: 3, product_sku: "ЮП-3270" }),
      makeTask({ task_id: 4, product_sku: "ЮП-3270" }),
    ]);

    const groups = groupsOf(items);
    expect(groups).toHaveLength(2);
    expect(groups.map((group) => group.productSku)).toEqual(["ЮП-2083", "ЮП-3270"]);
  });

  it("сводит `null` и `{}` в один безразмерный ключ, но не сливает его с размерными строками", () => {
    const items = groupReadyTransfers([
      makeTask({ task_id: 1, dimensions: null, dimensions_label: null }),
      makeTask({ task_id: 2, dimensions: {}, dimensions_label: null }),
      makeTask({ task_id: 3, dimensions: { length_mm: 900 }, dimensions_label: "0,9 м" }),
    ]);

    expect(items).toHaveLength(2);
    const [dimensionless] = groupsOf(items);
    expect(dimensionless.rows.map((row) => row.task_id)).toEqual([1, 2]);
    expect(items[1].kind).toBe("single");
    expect(items[1].kind === "single" ? items[1].row.task_id : null).toBe(3);
  });

  it("оставляет единственную строку по ключу одиночной", () => {
    const items = groupReadyTransfers([makeTask({ task_id: 7 })]);

    expect(items).toHaveLength(1);
    expect(items[0].kind).toBe("single");
    expect(items[0].kind === "single" ? items[0].row.task_id : null).toBe(7);
  });

  it("суммирует transferable_quantity по строкам группы", () => {
    const items = groupReadyTransfers([
      makeTask({ task_id: 1, transferable_quantity: "50" }),
      makeTask({ task_id: 2, transferable_quantity: "25" }),
      makeTask({ task_id: 3, transferable_quantity: "10" }),
    ]);

    const [group] = groupsOf(items);
    expect(group.totalTransferable).toBe(85);
  });

  it("помечает группу финальной, только когда финальна каждая её строка", () => {
    const allFinal = groupReadyTransfers([
      makeTask({ task_id: 1, is_final: true, has_next_step: false }),
      makeTask({ task_id: 2, is_final: true, has_next_step: false }),
    ]);
    expect(groupsOf(allFinal)[0].allFinal).toBe(true);

    const mixed = groupReadyTransfers([
      makeTask({ task_id: 1, is_final: true, has_next_step: false }),
      makeTask({ task_id: 2, is_final: false, has_next_step: true }),
    ]);
    expect(groupsOf(mixed)[0].allFinal).toBe(false);

    // `!has_next_step` в UI — тот же финальный выпуск, что и `is_final`.
    const noNextStep = groupReadyTransfers([
      makeTask({ task_id: 1, is_final: false, has_next_step: false }),
      makeTask({ task_id: 2, is_final: false, has_next_step: false }),
    ]);
    expect(groupsOf(noNextStep)[0].allFinal).toBe(true);
  });

  it("отдаёт в common общее значение строк группы, а при расхождении — null", () => {
    const items = groupReadyTransfers([
      makeTask({ task_id: 1, route_stage_id: 131, operation_name: "Пила", sequence: 1 }),
      makeTask({ task_id: 2, route_stage_id: 147, operation_name: "Раскрой ЧПУ", sequence: 3 }),
    ]);

    const [group] = groupsOf(items);
    expect(group.common.operationName).toBeNull();
    expect(group.common.sequence).toBeNull();
    expect(group.common.dimensionsLabel).toBe("2,75 м");
    expect(group.common.nextOperationName).toBe("Дробеструй");
  });
});
