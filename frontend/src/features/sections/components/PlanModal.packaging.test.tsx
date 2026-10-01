/**
 * Печать транслирует доску: колонка «Упаковка» есть только у участка, где в
 * справочнике операций есть упаковочная операция (`Section.has_packaging`).
 *
 * Проверяется через окно печати: и состав печатного набора, и кнопки «Колонки
 * печати» — сохранённый на анодировании набор не должен печатать пустую
 * колонку на пиле.
 */
import { render, screen, within } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import type { SectionBoardTask } from "@/shared/api/shopfloor";
import { PlanModal } from "./PlanModal";

const SECTION_ID = 7;
const STORAGE_KEY = `plan-print-settings-${SECTION_ID}`;

function makeTask(): SectionBoardTask {
  return {
    id: 1,
    product_id: 1,
    product_sku: "SKU-A",
    section_plan_line_id: 1,
    plan_position_id: 1,
    route_step_id: 1,
    sequence: 1,
    operation_code: "op",
    operation_name: "Полировка",
    is_significant: true,
    planned_quantity: "20",
    status: "ready",
    cache: {
      available_quantity: "20",
      issued_quantity: "0",
      completed_quantity: "0",
      transferred_quantity: "0",
      received_quantity: "0",
      rejected_quantity: "0",
      remaining_quantity: "20",
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
  };
}

function renderModal(hasPackaging: boolean | undefined) {
  return render(
    <PlanModal
      open
      onOpenChange={vi.fn()}
      sectionId={SECTION_ID}
      sectionName="Пила"
      sectionCode="SAWING"
      hasPackaging={hasPackaging}
      tasks={[makeTask()]}
    />,
  );
}

function printedColumnTitles(): string[] {
  return within(screen.getByRole("table"))
    .getAllByRole("columnheader")
    .map((header) => header.textContent ?? "");
}

/** Набор, снятый на участке с упаковкой, — с колонкой «Упаковка». */
function storeSettingsWithPackaging() {
  localStorage.setItem(
    STORAGE_KEY,
    JSON.stringify({ columns: ["sku", "packaging"], title: "" }),
  );
}

describe("окно печати: «Упаковка» только у участка с упаковочными операциями", () => {
  beforeEach(() => {
    localStorage.clear();
  });

  it("без упаковочных операций колонки нет ни в листе, ни в кнопках", () => {
    storeSettingsWithPackaging();

    renderModal(false);

    expect(printedColumnTitles()).not.toContain("Упаковка");
    expect(screen.queryByRole("button", { name: "Упаковка" })).toBeNull();
  });

  it("с упаковочными операциями сохранённый набор печатается целиком", () => {
    storeSettingsWithPackaging();

    renderModal(true);

    expect(printedColumnTitles()).toContain("Упаковка");
    expect(screen.queryByRole("button", { name: "Упаковка" })).not.toBeNull();
  });

  it("флаг не пришёл — колонка остаётся: ошибка справочника не прячет данные", () => {
    storeSettingsWithPackaging();

    renderModal(undefined);

    expect(printedColumnTitles()).toContain("Упаковка");
  });
});
