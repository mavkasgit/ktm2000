import { describe, expect, it } from "vitest";

import type { ImportOperationStep } from "@/shared/api/stock";

import { pillRowNaturalWidth } from "./previewPillWidths";

/** Подпись фиксированной ширины: chrome тестируется отдельно от текста. */
const measure = (text: string) => text.length * 10;

function step(overrides: Partial<ImportOperationStep> = {}): ImportOperationStep {
  return {
    sequence: 1,
    section_code: "RAW",
    section_name: "Подготовительный",
    operation_code: "CUT",
    operation_name: "Резка",
    is_significant: true,
    ...overrides,
  };
}

describe("ширина ряда пилюль", () => {
  it("нет этапов — нулевая ширина: ячейка печатает одну подпись", () => {
    expect(pillRowNaturalWidth([], null, measure)).toBe(0);
    expect(pillRowNaturalWidth(null, null, measure)).toBe(0);
  });

  it("одна пилюля без иконки: padding 12 + бордер 2 + текст", () => {
    // «Резка» = 5 символов × 10 = 50
    expect(pillRowNaturalWidth([step()], null, measure)).toBe(12 + 2 + 50);
  });

  it("иконка добавляет 12 + 4, акцентный цвет снимает бордер", () => {
    const withIcon = step({
      op_icon: "scissors",
      op_icon_color: "#ff0000",
    });
    expect(pillRowNaturalWidth([withIcon], null, measure)).toBe(12 + 12 + 4 + 50);
  });

  it("иконка приходит из справочника операций по имени", () => {
    const reference = step({
      operation_name: "Резка",
      op_icon: "scissors",
      op_icon_color: "#00ff00",
    });
    const width = pillRowNaturalWidth(
      [step({ sequence: 1 })],
      [reference],
      measure,
    );
    expect(width).toBe(12 + 12 + 4 + 50);
  });

  it("две пилюли в группе: разделитель «·» и зазор 2 px", () => {
    const steps = [
      step({ sequence: 1, operation_name: "Резка" }),
      step({ sequence: 1, operation_name: "Сшив" }),
    ];
    // «Резка» 64 + «Сшив» 54 + «·» 10 + два зазора gap-0.5 (2+2)
    expect(pillRowNaturalWidth(steps, null, measure)).toBe(64 + 54 + 10 + 4);
  });

  it("новая группа: разделитель «›» с padding 4 и зазор", () => {
    const steps = [
      step({ sequence: 1, operation_name: "Резка" }),
      step({ sequence: 2, operation_name: "Сшив" }),
    ];
    // 2 пилюли (64 + 54) + «›» 10 + padding 4 + два зазора 4
    expect(pillRowNaturalWidth(steps, null, measure)).toBe(64 + 54 + 10 + 4 + 4);
  });
});
