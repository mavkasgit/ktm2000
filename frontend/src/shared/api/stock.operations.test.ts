/**
 * Два пустых состояния оси (ADR-0055) — РАЗНЫЕ значения ключа остатка, но
 * ОДНА подпись ячейки: прочерк. Различие держат серверные подписи
 * (`completedOperationsServerLabel`): их разбирает фильтр, и по ним
 * различаются группы в списках выбора. Схлопывание серверных подписей
 * означало бы, что два разных остатка неразличимы в фильтре и в группировке
 * выдачи остатков; прочерк в ячейке — только глаз оператора.
 */
import { describe, expect, it } from "vitest";

import {
  OPERATIONS_EMPTY_LABEL,
  OPERATIONS_NOT_RECORDED_LABEL,
  completedOperationsServerLabel,
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

describe("formatCompletedOperationsLabel (ячейка)", () => {
  it("оба пустых состояния печатают прочерк", () => {
    expect(formatCompletedOperationsLabel(null)).toBe("—");
    expect(formatCompletedOperationsLabel([])).toBe("—");
    expect(formatCompletedOperationsLabel(undefined, [])).toBe("—");
    // …и при наличии справочника тоже: различает значение, а не подпись.
    expect(formatCompletedOperationsLabel(null, [STAGE])).toBe("—");
    expect(formatCompletedOperationsLabel([], [STAGE])).toBe("—");
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
    expect(formatCompletedOperationsLabel(undefined, [])).toBe("—");
  });

  it("при наличии справочника печатаются ИМЕНА, а не коды", () => {
    // Фильтр колонки работает по operation_name, поэтому подпись обязана
    // показывать то же самое; код остаётся запасным путём.
    const stage = { ...STAGE, operation_code: "rezka_code", operation_name: "Резка" };
    expect(formatCompletedOperationsLabel(["rezka_code"], [stage])).toBe("Резка");
    expect(formatCompletedOperationsLabel(["rezka_code"])).toBe("rezka_code");
  });
});

describe("completedOperationsServerLabel (фильтр и ключ)", () => {
  it("null → «не зафиксировано», [] → «без операций»", () => {
    expect(completedOperationsServerLabel(null)).toBe(OPERATIONS_NOT_RECORDED_LABEL);
    expect(completedOperationsServerLabel([])).toBe(OPERATIONS_EMPTY_LABEL);
    expect(completedOperationsServerLabel(null, [STAGE])).toBe(OPERATIONS_NOT_RECORDED_LABEL);
    expect(completedOperationsServerLabel([], [STAGE])).toBe(OPERATIONS_EMPTY_LABEL);
  });

  it("два пустых состояния различимы — их не схлопывает ни ячейка, ни справочник", () => {
    expect(completedOperationsServerLabel(null)).not.toBe(completedOperationsServerLabel([]));
    expect(completedOperationsServerLabel(null, [STAGE])).not.toBe(
      completedOperationsServerLabel([], [STAGE]),
    );
    expect(formatCompletedOperationsLabel(null)).toBe(formatCompletedOperationsLabel([]));
  });

  it("непустой список печатает имена, а не подписи пустых состояний", () => {
    expect(completedOperationsServerLabel(["rezka"], [STAGE])).toBe("Резка");
    expect(formatCompletedOperationsLabel(["rezka"], [STAGE])).toBe("Резка");
  });
});
