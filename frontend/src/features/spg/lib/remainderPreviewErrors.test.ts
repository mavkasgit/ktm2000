/**
 * Правила текста ячеек предпросмотра (#483): одна реализация на ячейку и на
 * модель ширин. Если они разойдутся, предсказанная высота строки перестанет
 * совпадать с напечатанным текстом.
 */
import { describe, expect, it } from "vitest";

import type { RemainderImportItem } from "@/shared/api/stock";

import {
  previewErrorsCellText,
  previewErrorsText,
  previewErrorsWraps,
  previewNameCellClass,
  previewNameCellText,
} from "./remainderPreviewErrors";

function item(overrides: Partial<RemainderImportItem> = {}): RemainderImportItem {
  return {
    status: "valid",
    product_name: null,
    source_name: null,
    errors: [],
    warnings: [],
    skip_reason_label: null,
    ...overrides,
  } as RemainderImportItem;
}

describe("текст ячеек предпросмотра", () => {
  it("наименование: каталог, иначе 1С, иначе прочерк", () => {
    expect(previewNameCellText(item({ product_name: "Кант", source_name: "Кант 1С" }))).toBe(
      "Кант",
    );
    expect(previewNameCellText(item({ source_name: "Кант 1С" }))).toBe("Кант 1С");
    expect(previewNameCellText(item())).toBe("—");
  });

  it("наименование переносится только в ветке полного текста (#489 baseline → truncate)", () => {
    expect(previewNameCellClass(true)).toBe("whitespace-pre-line");
    expect(previewNameCellClass(false)).toBe("truncate");
  });

  it("ошибки: у пропуска — подпись причины, одной строкой", () => {
    const skipped = item({ status: "skipped", skip_reason_label: "есть в исключениях" });
    expect(previewErrorsCellText(skipped)).toBe("Пропущено: есть в исключениях");
    expect(previewErrorsWraps(skipped)).toBe(false);
  });

  it("ошибки: у остальных только errors, предупреждения — в фильтр", () => {
    const withWarnings = item({
      warnings: ["предупреждение"],
      errors: ["ошибка импорта"],
    });
    expect(previewErrorsCellText(withWarnings)).toBe("ошибка импорта");
    expect(previewErrorsText(withWarnings)).toBe("предупреждение, ошибка импорта");
    expect(previewErrorsWraps(withWarnings)).toBe(true);
    expect(previewErrorsCellText(item())).toBe("—");
    // Ячейка печатает только `errors`: «Ошибка» — подпись фильтра.
    expect(previewErrorsCellText(item({ status: "invalid" }))).toBe("—");
    expect(previewErrorsText(item({ status: "invalid" }))).toBe("Ошибка");
  });
});
