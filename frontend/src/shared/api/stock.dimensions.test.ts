/**
 * Канон подписи размера — единственный источник для всех экранов (#195).
 *
 * Вектора в блоке «канон backend» скопированы из
 * `backend/tests/test_dimensions_domain.py::TestFormatDimensions`. Локальный
 * расчёт на фронте и `format_dimensions` на бэкенде обязаны печатать одну и ту
 * же строку: доска считает подпись сама (в её ответе нет `dimensions_label`),
 * план и контроль выполнения берут готовую с сервера. Расхождение строк здесь
 * = расхождение колонки «Размер» между экранами.
 */
import { describe, expect, it } from "vitest";

import { formatDimensionsLabel } from "./stock";

describe("formatDimensionsLabel", () => {
  // --- канон backend: backend/tests/test_dimensions_domain.py:169-193 ---
  it("безразмерные: null и пустой объект → прочерк", () => {
    expect(formatDimensionsLabel(null)).toBe("—");
    expect(formatDimensionsLabel({})).toBe("—");
  });

  it.each([
    [2700, "2,7 м"],
    [2750, "2,75 м"],
    [900, "0,9 м"],
    [1000, "1 м"],
    [1350, "1,35 м"],
  ])("длина %i мм → «%s»", (mm, expected) => {
    expect(formatDimensionsLabel({ length_mm: mm })).toBe(expected);
  });

  it("длина-вещественное число канонизируется до целого", () => {
    expect(formatDimensionsLabel({ length_mm: 2700.0 })).toBe("2,7 м");
  });

  it("прочие ключи печатаются в каноническом порядке", () => {
    expect(formatDimensionsLabel({ width_mm: 1200, height_mm: 2400 })).toBe(
      "height_mm: 2400, width_mm: 1200",
    );
  });

  it("длина из строки (legacy-ответы Excel) читается как число", () => {
    expect(formatDimensionsLabel({ length_mm: "2750" })).toBe("2,75 м");
  });

  // --- одна подпись при любом источнике (#195, AC-4) ---
  it("подпись с сервера и локальный расчёт совпадают", () => {
    // Доска (нет dimensions_label) и план (есть) получают один и тот же размер.
    expect(formatDimensionsLabel({ length_mm: 2750 })).toBe(
      formatDimensionsLabel({ length_mm: 2750 }, "2,75 м"),
    );
  });

  it("серверная подпись имеет приоритет над локальным расчётом", () => {
    expect(formatDimensionsLabel({ length_mm: 2750 }, "2,75 м (раскрой)")).toBe(
      "2,75 м (раскрой)",
    );
  });

  it("прочерк сервера не затирается непустым локальным расчётом", () => {
    // Склад отдаёт «—» безразмерным; локальный расчёт обязан согласиться.
    expect(formatDimensionsLabel(null, "—")).toBe("—");
    expect(formatDimensionsLabel({}, "—")).toBe("—");
  });

  it("пустая серверная подпись не вытесняет локальный расчёт", () => {
    expect(formatDimensionsLabel({ length_mm: 900 }, "")).toBe("0,9 м");
    expect(formatDimensionsLabel({ length_mm: 900 }, null)).toBe("0,9 м");
  });
});
