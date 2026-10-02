import { beforeEach, describe, expect, it, vi } from "vitest";
import type { CreateTransferResponse, ReadyToTransferTask } from "@/shared/api/transfers";

vi.mock("@/shared/api/transfers", () => ({
  createTransfer: vi.fn(),
  finalReleaseTask: vi.fn(),
}));

import { createTransfer, finalReleaseTask } from "@/shared/api/transfers";
import { planTransferQuantities, runTransferBatch } from "./runTransferBatch";
import { readyRowIdentity } from "./groupReadyTransfers";

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

describe("runTransferBatch: количества, набранные оператором в строках", () => {
  const createdTransfer: CreateTransferResponse = {
    transfer_id: 1,
    transfer_no: "TR-1",
    status: "accepted",
    to_task_id: 2,
  };

  beforeEach(() => {
    vi.mocked(createTransfer).mockReset().mockResolvedValue(createdTransfer);
    vi.mocked(finalReleaseTask).mockReset().mockResolvedValue({ transaction_id: 1, task_id: 2 });
  });

  function calledQuantity(call: number): string | number | undefined {
    const options = vi.mocked(createTransfer).mock.calls[call]?.[0];
    return options?.quantity;
  }

  it("строка уходит набранным числом, а строка без записи — своим доступным", async () => {
    const rows = rowsWithTransferable("100", "100");

    await runTransferBatch({
      rows,
      idempotencyPrefix: "t",
      quantities: { [readyRowIdentity(rows[0])]: "40" },
    });

    expect(calledQuantity(0)).toBe("40");
    expect(calledQuantity(1)).toBe("100");
  });

  it("превышение доступного разрешает только у набранного числа", async () => {
    const rows = rowsWithTransferable("100", "100");

    await runTransferBatch({
      rows,
      idempotencyPrefix: "t",
      quantities: { [readyRowIdentity(rows[0])]: "150" },
    });

    expect(vi.mocked(createTransfer).mock.calls[0]?.[0]?.allow_over_plan).toBe(true);
    expect(vi.mocked(createTransfer).mock.calls[1]?.[0]?.allow_over_plan).toBe(false);
  });

  it("обнулённая строка пропускается, остальные уходят", async () => {
    const rows = rowsWithTransferable("100", "100");

    const outcome = await runTransferBatch({
      rows,
      idempotencyPrefix: "t",
      quantities: {
        [readyRowIdentity(rows[0])]: "0",
        [readyRowIdentity(rows[1])]: "70",
      },
    });

    expect(calledQuantity(0)).toBe("70");
    expect(vi.mocked(createTransfer)).toHaveBeenCalledTimes(1);
    expect(outcome.results.map((result) => result.status)).toEqual(["skipped", "success"]);
  });
});
