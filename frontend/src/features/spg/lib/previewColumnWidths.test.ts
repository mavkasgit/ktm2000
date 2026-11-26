import { describe, expect, it } from "vitest";

import {
  PREVIEW_COLUMN_SPECS,
  PREVIEW_MIN_ROW_HEIGHT_PX,
  PREVIEW_ROW_PADDING_PX,
  PREVIEW_TABLE_MIN_WIDTH_PX,
  computePreviewColumnWidths,
  pillsFloorWidth,
  pillsTruncatedShareAt,
  pillsTruncationLimitAtWidth,
  predictRowHeight,
} from "./previewColumnWidths";
import type {
  PreviewFont,
  PreviewRowMeasurement,
  PreviewTextMeasurer,
} from "./previewTextMeasurer";

const errorsFont: PreviewFont = {
  family: "Test Sans",
  sizePx: 11,
  weight: 500,
  lineHeightPx: 15.125,
};
const pillFont: PreviewFont = { ...errorsFont, sizePx: 10, weight: 500, lineHeightPx: 20 };
const fonts = { errors: errorsFont, pill: pillFont };

/** Детерминированный измеритель: 6 px на символ, слова — по пробелам. */
function fakeMeasurer(): PreviewTextMeasurer {
  return {
    prepare: (text) => ({ text }),
    naturalWidth: (prepared) => (prepared as { text: string }).text.length * 6,
    maxWordWidth: (prepared) =>
      Math.max(
        0,
        ...(prepared as { text: string }).text
          .split(/\s+/)
          .filter(Boolean)
          .map((word) => word.length * 6),
      ),
    lineCount: (prepared, usable) => {
      const text = (prepared as { text: string }).text;
      if (!text) return 1;
      return Math.max(1, Math.ceil((text.length * 6) / usable));
    },
  };
}

function rows(count: number, pillWidth = 120): PreviewRowMeasurement[] {
  return Array.from({ length: count }, (_, index) => ({
    rowKey: index + 1,
    errorsText: "Ошибка в строке импорта",
    errorsWraps: true,
    pillWidth,
  }));
}

function compute(overrides: Partial<Parameters<typeof computePreviewColumnWidths>[0]> = {}) {
  return computePreviewColumnWidths({
    containerWidth: 1500,
    rows: rows(100),
    measurer: fakeMeasurer(),
    fonts,
    ...overrides,
  });
}

describe("раскладка предпросмотра", () => {
  it("политика объявлена для каждой колонки, доли дают 95%", () => {
    expect(PREVIEW_COLUMN_SPECS).toHaveLength(11);
    const sum = PREVIEW_COLUMN_SPECS.reduce((total, spec) => total + spec.baselineShare, 0);
    expect(sum).toBeCloseTo(95, 5);
    expect(PREVIEW_COLUMN_SPECS.filter((spec) => spec.policy === "fixed")).toHaveLength(8);
    expect(PREVIEW_COLUMN_SPECS.find((spec) => spec.id === "errors")?.policy).toBe("wrap");
    expect(PREVIEW_COLUMN_SPECS.find((spec) => spec.id === "operations")?.policy).toBe("pills");
    expect(PREVIEW_COLUMN_SPECS.find((spec) => spec.id === "source_name")?.policy).toBe(
      "truncate",
    );
  });

  it("сумма процентов содержательных колонок — 95 (служебные добавят 5)", () => {
    const result = compute();
    const sum = Object.values(result.shares).reduce(
      (total, share) => total + Number.parseFloat(share),
      0,
    );
    expect(sum).toBeCloseTo(95, 1);
  });

  it("ширины не опускаются ниже minPx даже на минимальной таблице", () => {
    const result = compute({ containerWidth: 600 });
    for (const spec of PREVIEW_COLUMN_SPECS) {
      expect(result.widthsPx[spec.id], spec.id).toBeGreaterThanOrEqual(spec.minPx - 0.01);
    }
    expect(result.tableWidthPx).toBe(PREVIEW_TABLE_MIN_WIDTH_PX);
  });

  it("ошибки получают остаток бюджета: шире ошибки — не больше строк", () => {
    const narrow = compute({ containerWidth: 1180 });
    const wide = compute({ containerWidth: 1920 });
    expect(wide.errorsWidthPx).toBeGreaterThan(narrow.errorsWidthPx);
    expect(wide.errorsLinesTotal).toBeLessThanOrEqual(narrow.errorsLinesTotal);
  });

  it("расчёт детерминирован: те же входы дают те же ширины и высоты", () => {
    const first = compute();
    const second = compute();
    expect(second.shares).toEqual(first.shares);
    expect([...second.rowHeights]).toEqual([...first.rowHeights]);
    expect(second.errorsWidthPx).toBe(first.errorsWidthPx);
  });

  it("на 1500 ошибкам достаётся больше текущих 11%, пилюли не сужаются", () => {
    const pillWidths = Array.from({ length: 500 }, (_, index) => 180 + (index % 200));
    const measured = rows(500).map((row, index) => ({
      ...row,
      pillWidth: pillWidths[index],
    }));
    const result = compute({ containerWidth: 1500, rows: measured });
    const errorsShare = result.errorsWidthPx / result.contentWidthPx;
    expect(errorsShare).toBeGreaterThan(0.15);
    expect(errorsShare).toBeLessThan(0.3);
    expect(result.widthsPx.operations).toBeGreaterThanOrEqual(0.21 * 1500 - 0.01);
    expect(result.widthsPx.source_name).toBe(90);
    expect(result.overflow).toBe(false);
  });
});

describe("лимит пилюль", () => {
  it("нижняя граница — квантиль: обрезано не больше лимита строк", () => {
    const widths = Array.from({ length: 100 }, (_, index) => 100 + index);
    const floor = pillsFloorWidth(widths, 0.1, 90, 12);
    const share = pillsTruncatedShareAt(widths, floor, 12);
    expect(share).toBeLessThanOrEqual(0.1);
    // Квантиль, а не «самая широкая строка»: 90% рядов уже помещаются.
    expect(floor).toBe(189 + 12);
  });

  it("лимит по ширине таблицы берётся из текущего фикса и не убывает", () => {
    const wide = pillsTruncationLimitAtWidth(1920);
    const mid = pillsTruncationLimitAtWidth(1500);
    const narrow = pillsTruncationLimitAtWidth(1180);
    expect(narrow).toBeCloseTo(0.3279, 4);
    expect(mid).toBeCloseTo(0.1297, 4);
    expect(wide).toBeCloseTo(0.0001, 4);
    expect(mid).toBeLessThan(narrow);
    expect(wide).toBeLessThan(mid);
  });

  it("«Операции» не уже нижней границы по пилюлям", () => {
    const result = compute({
      rows: rows(100, 400),
      pillLimitShare: 0.1,
    });
    const operations = result.widthsPx.operations;
    expect(operations).toBeGreaterThanOrEqual(result.pillsFloorPx - 0.01);
    expect(result.pillsTruncatedShare).toBeLessThanOrEqual(0.1 + 1e-9);
  });

  it("«Операции» не сужаются ниже текущей доли: лимит «не хуже текущего»", () => {
    const result = compute({ rows: rows(100, 120) });
    const spec = PREVIEW_COLUMN_SPECS.find((column) => column.id === "operations");
    expect(spec).toBeDefined();
    const current = (spec!.baselineShare / 100) * result.tableWidthPx;
    expect(result.widthsPx.operations).toBeGreaterThanOrEqual(current - 0.01);
  });

  it("неразрешимый бюджет — переполнение, а не нарушение minPx", () => {
    const result = compute({
      containerWidth: 1180,
      rows: rows(100, 6000),
    });
    expect(result.overflow).toBe(true);
    expect(result.minTableWidthPx).toBeGreaterThan(PREVIEW_TABLE_MIN_WIDTH_PX);
    for (const spec of PREVIEW_COLUMN_SPECS) {
      expect(result.widthsPx[spec.id]).toBeGreaterThanOrEqual(spec.minPx - 0.01);
    }
  });
});

describe("предсказанная высота строки", () => {
  it("минимум строки — 29 px, дальше lines × lineHeight + padding", () => {
    expect(predictRowHeight(1, 15.125)).toBe(PREVIEW_MIN_ROW_HEIGHT_PX);
    expect(predictRowHeight(2, 15.125)).toBeCloseTo(2 * 15.125 + PREVIEW_ROW_PADDING_PX, 5);
    expect(predictRowHeight(3, 20)).toBeCloseTo(65, 5);
  });

  it("пропуск не переносится: высота — минимум строки", () => {
    const longText = "Ошибка в строке импорта ".repeat(12);
    const items: PreviewRowMeasurement[] = [
      { rowKey: 1, errorsText: "Пропущено: есть в исключениях", errorsWraps: false, pillWidth: 100 },
      { rowKey: 2, errorsText: longText, errorsWraps: true, pillWidth: 100 },
    ];
    const result = compute({ rows: items });
    expect(result.rowHeights.get(1)).toBe(PREVIEW_MIN_ROW_HEIGHT_PX);
    expect(result.rowHeights.get(2)).toBeGreaterThan(PREVIEW_MIN_ROW_HEIGHT_PX);
  });
});
