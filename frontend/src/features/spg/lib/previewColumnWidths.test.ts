import { describe, expect, it } from "vitest";

import {
  ADAPTIVE_HEIGHT_THRESHOLD,
  PREVIEW_COLUMN_SPECS,
  PREVIEW_MIN_ROW_HEIGHT_PX,
  PREVIEW_ROW_PADDING_PX,
  PREVIEW_TABLE_MIN_WIDTH_PX,
  computePreviewColumnWidths,
  pillsFloorWidth,
  pillsTruncatedShareAt,
  pillsTruncationLimitAtWidth,
  predictRowHeight,
  resolveLayoutPolicy,
} from "./previewColumnWidths";
import type {
  PreviewFont,
  PreviewRowMeasurement,
  PreviewTextMeasurer,
} from "./previewTextMeasurer";

const nameFont: PreviewFont = {
  family: "Test Sans",
  sizePx: 11,
  weight: 400,
  lineHeightPx: 16.5,
};
const errorsFont: PreviewFont = {
  ...nameFont,
  weight: 500,
  lineHeightPx: 15.125,
};
const pillFont: PreviewFont = { ...errorsFont, sizePx: 10, lineHeightPx: 20 };
const fonts = { name: nameFont, errors: errorsFont, pill: pillFont };

/** Детерминированный измеритель: 6 px на символ, перенос по словам. */
function fakeMeasurer(): PreviewTextMeasurer {
  const natural = (text: string) => text.length * 6;
  return {
    prepare: (text) => ({ text }),
    naturalWidth: (prepared) => natural((prepared as { text: string }).text),
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
      return Math.max(1, Math.ceil(natural(text) / usable));
    },
  };
}

function row(index: number, overrides: Partial<PreviewRowMeasurement> = {}): PreviewRowMeasurement {
  return {
    rowKey: index + 1,
    nameText: "Наименование изделия для импорта",
    errorsText: "Ошибка в строке импорта",
    errorsWraps: true,
    pillWidth: 300,
    ...overrides,
  };
}

function rows(count: number, overrides: Partial<PreviewRowMeasurement> = {}): PreviewRowMeasurement[] {
  return Array.from({ length: count }, (_, index) => row(index, overrides));
}

function compute(overrides: Partial<Parameters<typeof computePreviewColumnWidths>[0]> = {}) {
  return computePreviewColumnWidths({
    containerWidth: 1500,
    rows: rows(100),
    measurer: fakeMeasurer(),
    fonts,
    // Тесты ниже — про сам аллокатор ширин (полный текст). Адаптивная
    // политика #489 проверяется отдельным блоком, где `auto` включается явно.
    layoutPolicy: "full-text",
    ...overrides,
  });
}

/** Тот же расчёт, но с правилом θ (#489) — как в проде. */
function computeAuto(
  overrides: Partial<Parameters<typeof computePreviewColumnWidths>[0]> = {},
) {
  return compute({ layoutPolicy: "auto", ...overrides });
}

describe("раскладка предпросмотра", () => {
  it("политика объявлена для каждой колонки, доли дают 95%", () => {
    expect(PREVIEW_COLUMN_SPECS).toHaveLength(11);
    const sum = PREVIEW_COLUMN_SPECS.reduce((total, spec) => total + spec.baselineShare, 0);
    expect(sum).toBeCloseTo(95, 5);
    expect(PREVIEW_COLUMN_SPECS.filter((spec) => spec.policy === "fixed")).toHaveLength(8);
    expect(PREVIEW_COLUMN_SPECS.find((spec) => spec.id === "source_name")?.policy).toBe("wrap");
    expect(PREVIEW_COLUMN_SPECS.find((spec) => spec.id === "errors")?.policy).toBe("wrap");
    expect(PREVIEW_COLUMN_SPECS.find((spec) => spec.id === "operations")?.policy).toBe("pills");
  });

  it("сумма процентов содержательных колонок — 95 (служебные добавят 5)", () => {
    const result = compute();
    const sum = Object.values(result.shares).reduce(
      (total, share) => total + Number.parseFloat(share),
      0,
    );
    expect(sum).toBeCloseTo(95, 1);
  });

  it("обе текстовые колонки получают минимум, бюджет распределён между ними", () => {
    const result = compute({ containerWidth: 1920 });
    const nameSpec = PREVIEW_COLUMN_SPECS.find((spec) => spec.id === "source_name")!;
    const errorsSpec = PREVIEW_COLUMN_SPECS.find((spec) => spec.id === "errors")!;
    expect(result.nameWidthPx).toBeGreaterThanOrEqual(nameSpec.minPx - 0.01);
    expect(result.errorsWidthPx).toBeGreaterThanOrEqual(errorsSpec.minPx - 0.01);
    // Бюджет текстовых колонок израсходован: фиксированные занимают 48%
    // таблицы, пилюли — не меньше 21%, остальное делят две текстовые.
    expect(result.nameWidthPx + result.errorsWidthPx).toBeGreaterThan(
      result.contentWidthPx * 0.25,
    );
  });

  it("полный текст: ни одна текстовая ячейка не обрезана и слово помещается", () => {
    const longRows = rows(100, {
      nameText: "Очень длинное наименование изделия с размерами и цветом ".repeat(2),
      errorsText: "Единица измерения 'упак' не поддерживается, нужна проверка ".repeat(2),
    });
    const result = compute({ rows: longRows });
    expect(result.textTruncatedCells).toBe(0);
    expect(result.wordOverflowCells).toBe(0);
    const measurer = fakeMeasurer();
    const nameUsable = result.nameWidthPx - 12;
    const errorsUsable = result.errorsWidthPx - 12;
    for (const item of longRows) {
      const namePrepared = measurer.prepare(item.nameText, nameFont);
      const errorsPrepared = measurer.prepare(item.errorsText, errorsFont);
      expect(measurer.maxWordWidth(namePrepared)).toBeLessThanOrEqual(nameUsable + 1);
      expect(measurer.maxWordWidth(errorsPrepared)).toBeLessThanOrEqual(errorsUsable + 1);
    }
  });

  it("бюджет делится по высоте: длинное имя отдаёт ширину наименованию", () => {
    const longNames = compute({
      rows: rows(100, { nameText: "Длинное наименование с размерами ".repeat(3), errorsText: "Ок" }),
    });
    const longErrors = compute({
      rows: rows(100, { nameText: "Коротко", errorsText: "Длинная ошибка импорта ".repeat(4) }),
    });
    expect(longNames.nameWidthPx).toBeGreaterThan(longErrors.nameWidthPx);
    expect(longErrors.errorsWidthPx).toBeGreaterThan(longNames.errorsWidthPx);
  });

  it("ширины не опускаются ниже minPx даже на минимальной таблице", () => {
    const result = compute({ containerWidth: 600 });
    for (const spec of PREVIEW_COLUMN_SPECS) {
      expect(result.widthsPx[spec.id], spec.id).toBeGreaterThanOrEqual(spec.minPx - 0.01);
    }
    expect(result.tableWidthPx).toBe(PREVIEW_TABLE_MIN_WIDTH_PX);
  });

  it("расчёт детерминирован: те же входы дают те же ширины и высоты", () => {
    const first = compute();
    const second = compute();
    expect(second.shares).toEqual(first.shares);
    expect([...second.rowHeights]).toEqual([...first.rowHeights]);
    expect(second.totalHeightPx).toBe(first.totalHeightPx);
  });

  it("подвыборка: ширины считаются на ≤300 строках, высоты — по всем", () => {
    const result = compute({ rows: rows(600), fitRows: 120 });
    expect(result.fitRows).toBe(120);
    expect(result.rowHeights.size).toBe(600);
  });
});

describe("лимит пилюль", () => {
  it("нижняя граница — квантиль: обрезано не больше лимита строк", () => {
    const widths = Array.from({ length: 100 }, (_, index) => 100 + index);
    const floor = pillsFloorWidth(widths, 0.1, 90, 12);
    expect(pillsTruncatedShareAt(widths, floor, 12)).toBeLessThanOrEqual(0.1);
    expect(floor).toBe(189 + 12);
  });

  it("лимит по ширине таблицы берётся из текущего фикса и не убывает", () => {
    expect(pillsTruncationLimitAtWidth(1180)).toBeCloseTo(0.3279, 4);
    expect(pillsTruncationLimitAtWidth(1500)).toBeCloseTo(0.1297, 4);
    expect(pillsTruncationLimitAtWidth(1920)).toBeCloseTo(0.0001, 4);
  });

  it("«Операции» не сужаются ниже текущей доли и не нарушают лимит", () => {
    const result = compute({ rows: rows(100, { pillWidth: 120 }), pillLimitShare: 0 });
    expect(result.widthsPx.operations).toBeGreaterThanOrEqual(0.21 * 1500 - 0.01);
    expect(result.pillsTruncatedShare).toBeLessThanOrEqual(result.pillsLimitShare + 1e-9);
  });

  it("неразрешимый бюджет — переполнение, а не нарушение minPx", () => {
    const result = compute({
      containerWidth: 1180,
      rows: rows(100, { pillWidth: 6000, nameText: "Слово".repeat(200), errorsText: "Слово".repeat(200) }),
    });
    expect(result.overflow).toBe(true);
    expect(result.minTableWidthPx).toBeGreaterThan(PREVIEW_TABLE_MIN_WIDTH_PX);
    for (const spec of PREVIEW_COLUMN_SPECS) {
      expect(result.widthsPx[spec.id]).toBeGreaterThanOrEqual(spec.minPx - 0.01);
    }
    expect(result.textTruncatedCells).toBe(0);
  });
});

describe("предсказанная высота строки", () => {
  it("минимум строки — 29 px, дальше lines × lineHeight + padding", () => {
    expect(predictRowHeight(1, 15.125)).toBe(PREVIEW_MIN_ROW_HEIGHT_PX);
    expect(predictRowHeight(2, 15.125)).toBeCloseTo(2 * 15.125 + PREVIEW_ROW_PADDING_PX, 5);
    expect(predictRowHeight(3, 20)).toBeCloseTo(65, 5);
  });

  it("высота — максимум по двум колонкам со своими line-height", () => {
    // Наименование 2 строки × 16.5 = 33 > ошибки 1 × 15.125 = 15.125.
    const result = compute({
      rows: rows(100, {
        nameText: "Наименование на две строки целиком",
        errorsText: "—",
      }),
      containerWidth: 1180,
    });
    const height = result.rowHeights.get(1)!;
    const expected = Math.max(
      PREVIEW_MIN_ROW_HEIGHT_PX,
      Math.max(2 * nameFont.lineHeightPx, errorsFont.lineHeightPx) + PREVIEW_ROW_PADDING_PX,
    );
    expect(height).toBeCloseTo(expected, 5);
    // 16.5 × 2 + 5 = 38 > 29: наименование, а не 20 px-контракт исследования.
    expect(height).toBeGreaterThan(2 * 20 + PREVIEW_ROW_PADDING_PX - 10);
  });

  it("пропуск не переносится: высота — по наименованию и минимуму", () => {
    const items: PreviewRowMeasurement[] = [
      row(0, { errorsText: "Пропущено: есть в исключениях", errorsWraps: false, nameText: "—" }),
    ];
    const result = compute({ rows: items });
    expect(result.rowHeights.get(1)).toBe(PREVIEW_MIN_ROW_HEIGHT_PX);
  });
});

describe("адаптивная политика (#489)", () => {
  /** Имя в две строки на максимально допустимой ширине наименования. */
  const LONG_NAME = "Соединитель декоративный армированный для профиля монтажа";

  function rowsWithLongNames(count: number): PreviewRowMeasurement[] {
    return rows(100, { nameText: "Плинтус 2,7 м", errorsText: "—" }).map((item, index) =>
      index < count ? { ...item, nameText: LONG_NAME } : item,
    );
  }

  it("порог θ = 5% зафиксирован; на границе — полный текст, выше — фикс", () => {
    expect(ADAPTIVE_HEIGHT_THRESHOLD).toBe(0.05);
    expect(resolveLayoutPolicy(1050, 1000)).toBe("full-text");
    expect(resolveLayoutPolicy(1050.01, 1000)).toBe("baseline");
    // Полный текст дешевле фикса (он и в #483 дал минус) — тоже полный.
    expect(resolveLayoutPolicy(973.4, 1000)).toBe("full-text");
    // Сравнивать не с чем — остаётся текущий фикс.
    expect(resolveLayoutPolicy(0, 0)).toBe("baseline");
  });

  it("граница проходит через реальный расчёт: 16 тяжёлых строк влезают в 5%, 17 — нет", () => {
    // Фикс: все строки по одной (29 px) — H_trunc = 2900. Допуск 5% = 3045 px.
    // Полный текст: длинное имя не влезает и в потолок колонки (2 строки,
    // 38 px), поэтому каждая тяжёлая строка стоит +9 px.
    const inside = computeAuto({ rows: rowsWithLongNames(16) });
    expect(inside.baselineHeightPx).toBeCloseTo(2900, 5);
    expect(inside.fullTextHeightPx).toBeCloseTo(16 * 38 + 84 * 29, 5);
    expect(inside.heightDeltaPct).toBeLessThanOrEqual(5);
    expect(inside.policy).toBe("full-text");

    const outside = computeAuto({ rows: rowsWithLongNames(17) });
    expect(outside.fullTextHeightPx).toBeCloseTo(17 * 38 + 83 * 29, 5);
    expect(outside.heightDeltaPct).toBeGreaterThan(5);
    expect(outside.policy).toBe("baseline");
  });

  it("дешёвый лист (realistic) → full-text: имена короткие, ошибок нет", () => {
    const result = computeAuto({
      rows: rows(100, { nameText: "Плинтус 2,7 м", errorsText: "—" }),
    });
    expect(result.policy).toBe("full-text");
    expect(result.textTruncatedCells).toBe(0);
    expect(result.heightDeltaPct).toBeLessThanOrEqual(5);
  });

  it("дорогой лист (long-tail) при 1180 → baseline на текущих долях", () => {
    const result = computeAuto({
      containerWidth: 1180,
      rows: rows(100, { nameText: LONG_NAME, errorsText: "—" }),
    });
    expect(result.policy).toBe("baseline");
    expect(result.heightDeltaPct).toBeGreaterThan(5);
    // Ширины — доли `remainderPreviewColumns`, а не посчитанные.
    expect(result.shares.source_name).toBe("15%");
    expect(result.shares.operations).toBe("21%");
    expect(result.shares.errors).toBe("11%");
    expect(result.nameWidthPx).toBeCloseTo(0.15 * 1180, 1);
    expect(result.pillsFloorPx).toBeCloseTo(0.21 * 1180, 1);
    // Имя в одну строку не влезает — это ровно текущий фикс, и он честно
    // сообщает, сколько ячеек обрезано.
    expect(result.textTruncatedCells).toBe(100);
    expect(result.wordOverflowCells).toBe(0);
  });

  it("в baseline высота строки — по «Ошибкам», наименование её не меняет", () => {
    // «Единица измерения не поддерживается» = 36 символов × 6 = 216 px:
    // на текущей доле «Ошибок» (11% от 1500 = 165, usable 153) это 2 строки.
    const errorsRows = rows(100, {
      nameText: LONG_NAME,
      errorsText: "Единица измерения не поддерживается",
    });
    const result = computeAuto({ rows: errorsRows });
    const expectedRow = Math.max(
      PREVIEW_MIN_ROW_HEIGHT_PX,
      Math.max(nameFont.lineHeightPx, 2 * errorsFont.lineHeightPx) + PREVIEW_ROW_PADDING_PX,
    );
    expect(result.policy).toBe("baseline");
    expect(result.rowHeights.size).toBe(100);
    for (const height of result.rowHeights.values()) {
      expect(height).toBeCloseTo(expectedRow, 5);
    }
    expect(result.totalHeightPx).toBeCloseTo(100 * expectedRow, 2);
    // Тот же лист с другими именами: высота baseline не зависит от имени.
    const shorterNames = computeAuto({
      rows: errorsRows.map((item) => ({ ...item, nameText: "Плинтус" })),
    });
    expect(shorterNames.baselineHeightPx).toBeCloseTo(result.baselineHeightPx, 5);
  });

  it("обе высоты посчитаны по всем строкам, а не по подвыборке ширины", () => {
    const result = computeAuto({
      rows: rows(600, { nameText: LONG_NAME, errorsText: "—" }),
      fitRows: 120,
    });
    expect(result.fitRows).toBe(120);
    expect(result.baselineHeightPx).toBeCloseTo(600 * PREVIEW_MIN_ROW_HEIGHT_PX, 5);
  });
});

