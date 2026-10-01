/**
 * Окно печати открывается на пресете участка: набор колонок даёт профиль
 * печати участка (`PRINT_PROFILES`), а колонка «Упаковка» есть только там, где
 * в справочнике операций участка есть упаковочная операция
 * (`Section.has_packaging`, ADR-0059).
 *
 * Проверяется через окно: и состав листа, и кнопки «Колонки печати», и какой
 * пресет подсвечен активным. Набор прошлого выбора применяется только тогда,
 * когда он совпал с названным пресетом участка: набор из старой версии
 * приложения или после ручной правки колонок профиль участка не перекрывает.
 */
import { fireEvent, render, screen, within } from "@testing-library/react";
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

function renderModal(opts: { sectionCode: string; hasPackaging?: boolean }) {
  return render(
    <PlanModal
      open
      onOpenChange={vi.fn()}
      sectionId={SECTION_ID}
      sectionName="Участок"
      sectionCode={opts.sectionCode}
      hasPackaging={opts.hasPackaging}
      tasks={[makeTask()]}
    />,
  );
}

/** Колонки листа: служебная отметка строки и колонка действий без подписи. */
function printedColumnTitles(): string[] {
  return within(screen.getByRole("table"))
    .getAllByRole("columnheader")
    .map((header) => header.textContent ?? "")
    .filter((title) => title !== "");
}

/** Активный пресет — единственный вариант кнопки со сплошной заливкой. */
function isPresetActive(name: RegExp): boolean {
  return screen.getByRole("button", { name }).className.includes("bg-primary");
}

function storeSettings(columns: string[]) {
  localStorage.setItem(STORAGE_KEY, JSON.stringify({ columns, title: "" }));
}

describe("Пресеты участка: «Упаковка» только у участка с упаковочными операциями", () => {
  beforeEach(() => {
    localStorage.clear();
  });

  it("без упаковочных операций колонки нет ни в листе, ни в кнопках", () => {
    renderModal({ sectionCode: "PACKING", hasPackaging: false });

    expect(printedColumnTitles()).not.toContain("Упаковка");
    expect(screen.queryByRole("button", { name: "Упаковка" })).toBeNull();
    expect(isPresetActive(/Базовый/)).toBe(true);
  });

  it("с упаковочными операциями набор участка печатается целиком", () => {
    renderModal({ sectionCode: "PACKING", hasPackaging: true });

    expect(printedColumnTitles()).toContain("Упаковка");
    expect(screen.queryByRole("button", { name: "Упаковка" })).not.toBeNull();
    expect(isPresetActive(/Базовый/)).toBe(true);
  });

  it("флаг не пришёл — колонка остаётся: ошибка справочника не прячет данные", () => {
    renderModal({ sectionCode: "PACKING", hasPackaging: undefined });

    expect(printedColumnTitles()).toContain("Упаковка");
  });
});

describe("Пресеты участка: что печатается при открытии", () => {
  beforeEach(() => {
    localStorage.clear();
  });

  it("базовый пресет участка открывается активным и совпадает с листом", () => {
    renderModal({ sectionCode: "SAWING" });

    expect(isPresetActive(/Базовый/)).toBe(true);
    expect(printedColumnTitles()).toEqual([
      "Артикул",
      "Размер",
      "Пред операции",
      "Операция",
      "Осталось",
    ]);
  });

  it("набор прошлого выбора применяется, если это названный пресет", () => {
    storeSettings(["sku", "size", "operation", "balance"]);

    renderModal({ sectionCode: "SAWING" });

    expect(isPresetActive(/Компактный/)).toBe(true);
    expect(printedColumnTitles()).toEqual([
      "Артикул",
      "Размер",
      "Операция",
      "Осталось",
    ]);
  });

  it("набор без пресета (старая версия, ручная правка) профиль участка не перекрывает", () => {
    storeSettings(["sku", "packaging"]);

    renderModal({ sectionCode: "SAWING" });

    expect(isPresetActive(/Базовый/)).toBe(true);
    expect(printedColumnTitles()).toEqual([
      "Артикул",
      "Размер",
      "Пред операции",
      "Операция",
      "Осталось",
    ]);
  });

  it("пресет «Только артикулы» печатает остаток вместе с артикулом", () => {
    renderModal({ sectionCode: "SAWING" });

    fireEvent.click(screen.getByRole("button", { name: /Только артикулы/ }));

    expect(isPresetActive(/Только артикулы/)).toBe(true);
    expect(printedColumnTitles()).toEqual(["Артикул", "Осталось"]);
  });
});
