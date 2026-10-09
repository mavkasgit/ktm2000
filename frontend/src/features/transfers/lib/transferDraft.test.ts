/**
 * Черновик массовой передачи (#325): распределение по группе, снятие нулевых
 * строк при отправке и сумма группы. Режимов «+N»/целевого значения у передач
 * нет — количество строки это ровно её доступное, пока оператор не набрал.
 */
import { describe, expect, it } from "vitest";
import type { ReadyToTransferTask } from "@/shared/api/transfers";

import { readyRowIdentity, type ReadyTransferGroup } from "./groupReadyTransfers";
import {
  draftGroupQuantity,
  draftRowInput,
  draftRowQuantity,
  draftRowsToSend,
  EMPTY_TRANSFER_DRAFT,
  withGroupInput,
  withRowInput,
} from "./transferDraft";

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
    makeTask({ task_id: index + 1, plan_position_id: index + 1, transferable_quantity }),
  );
}

function makeGroup(rows: ReadyToTransferTask[]): ReadyTransferGroup {
  return {
    kind: "group",
    key: "g1",
    productSku: "ЮП-2083",
    sectionId: 1,
    nextSectionId: 4,
    rows,
    totalTransferable: rows.reduce((sum, row) => sum + parseFloat(row.transferable_quantity), 0),
    totalPlanned: 0,
    totalAlreadyTransferred: 0,
    allFinal: false,
    hasNextStep: true,
    common: {
      dimensionsLabel: null,
      operationName: null,
      nextOperationName: null,
      nextSectionName: null,
    },
  };
}

describe("черновик массовой передачи", () => {
  it("строка без ввода идёт своим transferable_quantity", () => {
    const [row] = rowsWithTransferable("7");
    expect(draftRowQuantity(EMPTY_TRANSFER_DRAFT, row)).toBe("7");
    expect(draftRowInput(EMPTY_TRANSFER_DRAFT, row)).toBeUndefined();
  });

  it("правка строки хранит набранное по идентификатору строки", () => {
    const [row] = rowsWithTransferable("7");
    const draft = withRowInput(EMPTY_TRANSFER_DRAFT, null, row, "3");
    expect(draftRowInput(draft, row)).toBe("3");
    expect(draftRowQuantity(draft, row)).toBe("3");
    expect(draft.rowQuantities[readyRowIdentity(row)]).toBe("3");
  });

  it("распределение по группе: набранное раскладывается по строкам сверху вниз", () => {
    const rows = rowsWithTransferable("2", "0", "3");
    const group = makeGroup(rows);
    const draft = withGroupInput(EMPTY_TRANSFER_DRAFT, group, "4");
    expect(rows.map((row) => draftRowQuantity(draft, row))).toEqual(["2", "0", "2"]);
    expect(draft.groupQuantities[group.key]).toBe("4");
  });

  it("правка строки снимает набранное в шапке группы", () => {
    const rows = rowsWithTransferable("2", "3");
    const group = makeGroup(rows);
    const typed = withGroupInput(EMPTY_TRANSFER_DRAFT, group, "4");
    const afterRow = withRowInput(typed, group.key, rows[0], "1");
    expect(afterRow.groupQuantities[group.key]).toBeUndefined();
  });

  it("очистка шапки снимает раскладку: строки возвращаются к своему доступному", () => {
    const rows = rowsWithTransferable("2", "3");
    const group = makeGroup(rows);
    const typed = withGroupInput(EMPTY_TRANSFER_DRAFT, group, "4");
    const cleared = withGroupInput(typed, group, "");
    expect(rows.map((row) => draftRowQuantity(cleared, row))).toEqual(["2", "3"]);
    expect(cleared.groupQuantities[group.key]).toBe("");
  });

  it("сумма группы: набранное в шапке, иначе — сумма количеств её строк", () => {
    const rows = rowsWithTransferable("2", "3");
    const group = makeGroup(rows);
    expect(draftGroupQuantity(EMPTY_TRANSFER_DRAFT, group)).toBe("5");
    const typed = withGroupInput(EMPTY_TRANSFER_DRAFT, group, "4");
    expect(draftGroupQuantity(typed, group)).toBe("4");
  });

  it("снятие нулевых: хвост раскладки группы не отправляется", () => {
    const rows = rowsWithTransferable("2", "3");
    const group = makeGroup(rows);
    const draft = withGroupInput(EMPTY_TRANSFER_DRAFT, group, "2");
    expect(draftRowsToSend(draft, rows)).toEqual([rows[0]]);
  });
});
