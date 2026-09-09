import { describe, expect, it } from "vitest";

import type { QuantityPerHangerDict } from "@/shared/api/products";
import {
  effectiveForLength,
  effectiveForMode,
  entryForLength,
  isHangerAutoMode,
  isSheetState,
  lengthKey,
  manualByLength,
  normalizeLengths,
  primaryHangerValue,
  primaryLength,
  productLengths,
  sheetDims,
  sheetHangerEntry,
  sheetLengths,
} from "./hangerQuantity";

describe("lengthKey", () => {
  it("целые длины — без десятичной части (зеркало backend _length_key)", () => {
    expect(lengthKey(2780)).toBe("2780");
    expect(lengthKey(2780.0)).toBe("2780");
  });

  it("дробные длины сохраняют дробную часть", () => {
    expect(lengthKey(2780.5)).toBe("2780.5");
  });
});

describe("isHangerAutoMode", () => {
  it("оба поля заполнены и > 0 — авто-режим", () => {
    expect(isHangerAutoMode({ perimeter_mm: 64.2, mount_width_mm: 19.35 })).toBe(true);
  });

  it("нет хотя бы одного поля — ручной режим", () => {
    expect(isHangerAutoMode({ perimeter_mm: 64.2, mount_width_mm: null })).toBe(false);
    expect(isHangerAutoMode({ perimeter_mm: null, mount_width_mm: 19.35 })).toBe(false);
    expect(isHangerAutoMode({})).toBe(false);
  });

  it("нули и отрицательные значения — не авто-режим", () => {
    expect(isHangerAutoMode({ perimeter_mm: 0, mount_width_mm: 19.35 })).toBe(false);
    expect(isHangerAutoMode({ perimeter_mm: 64.2, mount_width_mm: -1 })).toBe(false);
  });
});

describe("normalizeLengths", () => {
  it("фильтрует мусор, дедуп и сортировка", () => {
    expect(normalizeLengths([3000, 2780, 3000, -5, NaN, null, undefined])).toEqual([2780, 3000]);
  });

  it("пусто — пустой список", () => {
    expect(normalizeLengths([])).toEqual([]);
    expect(normalizeLengths([null, undefined])).toEqual([]);
  });
});

describe("productLengths", () => {
  it("берёт только канон lengths_mm (product_lengths): legacy length_mm не подмешивается", () => {
    expect(
      productLengths({ lengths_mm: [3000, 2780, 3000, -5, NaN], length_mm: 2500 }),
    ).toEqual([2780, 3000]);
  });

  it("пусто — пустой список", () => {
    expect(productLengths({ lengths_mm: [], length_mm: null })).toEqual([]);
  });
});

describe("entryForLength / effectiveForLength", () => {
  const dict: QuantityPerHangerDict = {
    "2780": { auto: 72, manual: 60 },
    "3000": { auto: null, manual: 55 },
    "3500": { auto: null, manual: null },
  };

  it("режим auto — авто-значение записи (#127)", () => {
    expect(effectiveForLength(dict, 2780, "auto")).toEqual({ value: 72, source: "auto" });
    expect(effectiveForLength(dict, 3000, "auto")).toEqual({ value: null, source: "auto" });
  });

  it("режим manual — ручное значение записи (#127)", () => {
    expect(effectiveForLength(dict, 2780, "manual")).toEqual({ value: 60, source: "manual" });
    expect(effectiveForLength(dict, 3000, "manual")).toEqual({ value: 55, source: "manual" });
  });

  it("нет записи — значения нет, источник всё равно режим", () => {
    expect(effectiveForLength(dict, 9999, "auto")).toEqual({ value: null, source: "auto" });
    expect(effectiveForLength(null, 2780, "manual")).toEqual({ value: null, source: "manual" });
    expect(entryForLength(null, 2780)).toBeNull();
  });
});

describe("primaryLength", () => {
  it("явный primary_length_mm имеет приоритет", () => {
    expect(primaryLength({ primary_length_mm: 3500, lengths_mm: [2780, 3500] })).toBe(3500);
  });

  it("без явного — первая по возрастанию из канона; legacy length_mm не подмешивается", () => {
    expect(primaryLength({ primary_length_mm: null, lengths_mm: [3500, 2780] })).toBe(2780);
    expect(primaryLength({ primary_length_mm: null, lengths_mm: [], length_mm: 2780 })).toBeNull();
  });

  it("без длин — null", () => {
    expect(primaryLength({ primary_length_mm: null, lengths_mm: [] })).toBeNull();
  });
});

describe("primaryHangerValue", () => {
  it("режим auto — авто-значение основной длины (#127)", () => {
    const product = {
      primary_length_mm: 2780,
      lengths_mm: [2780, 3000],
      length_mm: null,
      hanger_mode: "auto" as const,
      quantity_per_hanger: {
        "2780": { auto: 72, manual: 60 },
        "3000": { auto: null, manual: 55 },
      } as QuantityPerHangerDict,
    };
    expect(primaryHangerValue(product)).toEqual({ lengthMm: 2780, value: 72, source: "auto" });
  });

  it("режим manual — ручное значение, без fallback на авто (#127)", () => {
    const product = {
      primary_length_mm: 2780,
      lengths_mm: [2780],
      length_mm: null,
      hanger_mode: "manual" as const,
      quantity_per_hanger: {
        "2780": { auto: 72, manual: 40 },
      } as QuantityPerHangerDict,
    };
    expect(primaryHangerValue(product)).toEqual({ lengthMm: 2780, value: 40, source: "manual" });
  });

  it("режим manual, ручное null — значения нет (авто не подменяет)", () => {
    const product = {
      lengths_mm: [2780],
      length_mm: null,
      hanger_mode: "manual" as const,
      quantity_per_hanger: { "2780": { auto: 72, manual: null } } as QuantityPerHangerDict,
    };
    expect(primaryHangerValue(product)).toBeNull();
  });

  it("нет режима — авто по умолчанию", () => {
    const product = {
      lengths_mm: [2780],
      length_mm: null,
      quantity_per_hanger: { "2780": { auto: 72, manual: 40 } } as QuantityPerHangerDict,
    };
    expect(primaryHangerValue(product)).toEqual({ lengthMm: 2780, value: 72, source: "auto" });
  });

  it("нет длин или словаря — null", () => {
    expect(primaryHangerValue({ lengths_mm: [], length_mm: null, quantity_per_hanger: null })).toBeNull();
    expect(
      primaryHangerValue({ lengths_mm: [2780], length_mm: null, quantity_per_hanger: null }),
    ).toBeNull();
  });
});

describe("manualByLength", () => {
  it("только non-null ручные значения", () => {
    expect(
      manualByLength({
        "2780": { auto: 72, manual: 60 },
        "3000": { auto: 70, manual: null },
      }),
    ).toEqual({ "2780": 60 });
    expect(manualByLength(null)).toEqual({});
  });
});

// ─── Листы 2D/3D (#126) ────────────────────────────────────────────────

describe("isSheetState", () => {
  it("area и volume — листы", () => {
    expect(isSheetState("area")).toBe(true);
    expect(isSheetState("volume")).toBe(true);
  });

  it("length и пусто — не листы", () => {
    expect(isSheetState("length")).toBe(false);
    expect(isSheetState(null)).toBe(false);
    expect(isSheetState(undefined)).toBe(false);
  });
});

describe("sheetDims / sheetLengths", () => {
  it("оси полотна из dimensions", () => {
    expect(sheetDims({ dimensions: { length_mm: 3000, width_mm: 1500, height_mm: 300 } })).toEqual({
      lengthMm: 3000,
      widthMm: 1500,
      heightMm: 300,
    });
  });

  it("нет словаря или оси — null", () => {
    expect(sheetDims({ dimensions: null })).toEqual({ lengthMm: null, widthMm: null, heightMm: null });
    expect(sheetDims({})).toEqual({ lengthMm: null, widthMm: null, heightMm: null });
    expect(sheetDims({ dimensions: { width_mm: 1500 } })).toEqual({ lengthMm: null, widthMm: 1500, heightMm: null });
  });

  it("длины полотна — ноль или одна запись", () => {
    expect(sheetLengths({ dimensions: { length_mm: 3000 } })).toEqual([3000]);
    expect(sheetLengths({ dimensions: { width_mm: 1500 } })).toEqual([]);
    expect(sheetLengths({})).toEqual([]);
  });
});

describe("effectiveForMode", () => {
  const entry = { auto: 2, manual: 5 };

  it("режим manual — ручное значение", () => {
    expect(effectiveForMode(entry, "manual")).toEqual({ value: 5, source: "manual" });
  });

  it("режим auto или пустой — авто-значение, источник всегда auto", () => {
    expect(effectiveForMode(entry, "auto")).toEqual({ value: 2, source: "auto" });
    expect(effectiveForMode(entry, null)).toEqual({ value: 2, source: "auto" });
    expect(effectiveForMode(entry, undefined)).toEqual({ value: 2, source: "auto" });
  });

  it("выбранное значение null — источник всё равно режим", () => {
    expect(effectiveForMode({ auto: null, manual: 5 }, "auto")).toEqual({ value: null, source: "auto" });
    expect(effectiveForMode({ auto: 2, manual: null }, "manual")).toEqual({ value: null, source: "manual" });
    expect(effectiveForMode(null, "manual")).toEqual({ value: null, source: "manual" });
  });
});

describe("sheetHangerEntry", () => {
  it("первая (единственная) запись словаря листа", () => {
    expect(sheetHangerEntry({ "3000": { auto: 2, manual: null } })).toEqual({ auto: 2, manual: null });
  });

  it("пусто или нет словаря — null", () => {
    expect(sheetHangerEntry({})).toBeNull();
    expect(sheetHangerEntry(null)).toBeNull();
    expect(sheetHangerEntry(undefined)).toBeNull();
  });
});
