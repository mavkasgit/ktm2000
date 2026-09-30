/**
 * Три состояния выполненных операций остатка (ADR-0055) обязаны печатать
 * РАЗНЫЕ подписи: `null` — операции вне маршрута, `[]` — маршрут пройден без
 * операций, список — конкретные операции. Схлопывание любой пары означает, что
 * два разных остатка (разные `completed_operations` → разные строки бэкенда)
 * станут неразличимыми в колонке «Операции», в фильтре и в группировке выдачи
 * остатков.
 */
import { describe, expect, it } from "vitest";

import {
  OPERATIONS_EMPTY_LABEL,
  OPERATIONS_NOT_RECORDED_LABEL,
  formatCompletedOperationsLabel,
} from "./stock";

const STAGE = {
  sequence: 1,
  section_code: "rez",
  section_name: "Резка",
  operation_code: "rezka",
  operation_name: "Резка",
  is_significant: true,
};

describe("formatCompletedOperationsLabel", () => {
  it("null → операции вне маршрута", () => {
    expect(formatCompletedOperationsLabel(null)).toBe(OPERATIONS_NOT_RECORDED_LABEL);
  });

  it("[] → маршрут пройден, операций не было", () => {
    expect(formatCompletedOperationsLabel([])).toBe(OPERATIONS_EMPTY_LABEL);
  });

  it("null и [] печатают разные подписи", () => {
    expect(formatCompletedOperationsLabel(null)).not.toBe(formatCompletedOperationsLabel([]));
  });

  it("список операций печатается через запятую", () => {
    expect(formatCompletedOperationsLabel(["Резка", "Пайка"])).toBe("Резка, Пайка");
  });

  it("два разных списка операций дают разные подписи", () => {
    expect(formatCompletedOperationsLabel(["Резка"])).not.toBe(
      formatCompletedOperationsLabel(["Пайка"]),
    );
  });

  it("ответ без поля completed_operations откатывается на подписи этапов", () => {
    expect(formatCompletedOperationsLabel(undefined, [STAGE])).toBe("Резка");
    expect(formatCompletedOperationsLabel(undefined, [])).toBe(OPERATIONS_NOT_RECORDED_LABEL);
  });

  it("при наличии справочника печатаются ИМЕНА, а не коды", () => {
    // Фильтр колонки работает по operation_name, поэтому подпись обязана
    // показывать то же самое; код остаётся запасным путём.
    const stage = { ...STAGE, operation_code: "rezka_code", operation_name: "Резка" };
    expect(formatCompletedOperationsLabel(["rezka_code"], [stage])).toBe("Резка");
    expect(formatCompletedOperationsLabel(["rezka_code"])).toBe("rezka_code");
  });

  it("пустые состояния различаются и при наличии справочника", () => {
    expect(formatCompletedOperationsLabel(null, [STAGE])).toBe(OPERATIONS_NOT_RECORDED_LABEL);
    expect(formatCompletedOperationsLabel([], [STAGE])).toBe(OPERATIONS_EMPTY_LABEL);
  });
});