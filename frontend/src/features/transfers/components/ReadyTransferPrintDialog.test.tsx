/**
 * Лист печати «Готово к передаче»: что печатается и в каком виде.
 *
 * Экран и бумага расходятся осознанно: на листе нет колонки ID строки (оператор
 * ищет по артикулу, размеру и адресату), а код участка латиницей («/ WIP_STOCK»)
 * заменён названием — то же, что читает оператор в колонке «Следующий».
 */

import { render, screen, within } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import type { ReadyToTransferTask } from "@/shared/api/transfers";
import { ReadyTransferPrintDialog } from "./ReadyTransferPrintDialog";

function makeTask(overrides: Partial<ReadyToTransferTask> = {}): ReadyToTransferTask {
  return {
    task_id: 1,
    section_id: 1,
    section_code: "SAW",
    section_name: "Пила",
    plan_position_id: 1453,
    route_stage_id: 131,
    sequence: 1,
    operation_code: "010",
    operation_name: "Окно",
    product_id: 42,
    product_sku: "АТ-6324",
    planned_quantity: "900",
    completed_quantity: "540",
    already_transferred_quantity: "0",
    transferable_quantity: "540",
    has_next_step: true,
    next_section_id: 5,
    next_section_code: "WIP_STOCK",
    next_section_name: "Склад незавершённого производства",
    next_operation_name: "Дробеструй",
    next_step_sequence: 2,
    next_step_is_final: false,
    is_final: false,
    dimensions: { length_mm: 2700 },
    dimensions_label: "2,7 м",
    ...overrides,
  };
}

function renderSheet(rows: ReadyToTransferTask[]) {
  render(
    <ReadyTransferPrintDialog open onOpenChange={() => {}} rows={rows} scopeLabel="Все ГХП" />,
  );
  const table = screen.getByRole("table");
  return {
    headers: within(table)
      .getAllByRole("columnheader")
      .map((cell) => cell.textContent?.trim()),
    bodyRows: within(table).getAllByRole("row").slice(1),
  };
}

describe("ReadyTransferPrintDialog", () => {
  it("печатает адресата названием, без кода участка", () => {
    const { bodyRows } = renderSheet([makeTask()]);

    const cells = within(bodyRows[0]).getAllByRole("cell").map((cell) => cell.textContent?.trim());
    expect(cells).toContain("Дробеструй");
    expect(cells.join(" | ")).not.toContain("WIP_STOCK");
  });

  it("не печатает ID строки", () => {
    const { headers, bodyRows } = renderSheet([makeTask()]);

    expect(headers).not.toContain("ID");
    const cells = within(bodyRows[0]).getAllByRole("cell").map((cell) => cell.textContent?.trim());
    expect(cells).not.toContain("1453");
    // Колонок ровно столько же, сколько заголовков — ID не «съел» сдвиг.
    expect(cells).toHaveLength(headers.length);
  });

  it("финальную строку печатает как «Финальный», а не прочерком", () => {
    const { bodyRows } = renderSheet([
      makeTask({ has_next_step: false, is_final: true, next_operation_name: null, next_section_name: null }),
    ]);

    const cells = within(bodyRows[0]).getAllByRole("cell").map((cell) => cell.textContent?.trim());
    expect(cells).toContain("Финальный");
  });
});
