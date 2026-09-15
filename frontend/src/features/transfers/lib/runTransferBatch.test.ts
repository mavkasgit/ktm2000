import { describe, expect, it } from "vitest";
import type { ReadyToTransferTask } from "@/shared/api/transfers";
import { planTransferQuantities } from "./runTransferBatch";

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

function rowsWithTransferable(...quantities: string[]): ReadyToTransferTask[] {
  return quantities.map((transferable_quantity, index) =>
    makeTask({
      task_id: index + 1,
      plan_position_id: index + 1,
      transferable_quantity,
    }),
  );
}

describe("planTransferQuantities", () => {
  it("без общего количества отправляет каждую строку её собственным transferable_quantity", () => {
    const plan = planTransferQuantities(rowsWithTransferable("0.9", "1.35", "2.7"));

    expect(plan.quantities).toEqual(["0.9", "1.35", "2.7"]);
    expect(plan.undistributed).toBe(0);
  });

  it("меньше суммы: строки забирают своё по порядку, последняя получает частичный остаток", () => {
    const plan = planTransferQuantities(rowsWithTransferable("0.9", "1.35", "1.8"), 3);

    expect(plan.quantities).toEqual(["0.9", "1.35", "0.75"]);
    expect(plan.undistributed).toBe(0);
  });

  it("больше суммы: каждая строка получает свой transferable, а излишек уходит в undistributed", () => {
    const plan = planTransferQuantities(rowsWithTransferable("0.9", "1.35", "1.8"), 5);

    expect(plan.quantities).toEqual(["0.9", "1.35", "1.8"]);
    expect(plan.undistributed).toBe(0.95);
  });

  it("ровно сумма: распределяется целиком, undistributed равен нулю", () => {
    const plan = planTransferQuantities(rowsWithTransferable("0.9", "1.35"), 2.25);

    expect(plan.quantities).toEqual(["0.9", "1.35"]);
    expect(plan.undistributed).toBe(0);
  });

  it("дробный остаток последней строки не обрастает хвостом float", () => {
    const plan = planTransferQuantities(rowsWithTransferable("1.1", "2.2"), 2.5);

    expect(plan.quantities).toEqual(["1.1", "1.4"]);
    expect(plan.undistributed).toBe(0);
  });

  it("нулевой transferable у средней строки не сдвигает распределение остальным", () => {
    const plan = planTransferQuantities(rowsWithTransferable("2", "0", "3"), 4);

    expect(plan.quantities).toEqual(["2", "0", "2"]);
    expect(plan.undistributed).toBe(0);
  });
});
