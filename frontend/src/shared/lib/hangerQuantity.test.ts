import { describe, expect, it } from "vitest";

import type { ProductLength, QuantityPerHangerDict } from "@/shared/api/products";
import {
  effectiveForLength,
  effectiveForMode,
  effectiveRawLength,
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

const length = (
  length_mm: number,
  raw_length_mm: number | null = null,
  is_primary = false,
): ProductLength => ({ length_mm, raw_length_mm, is_primary });

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
  it("фильтрует мусор, дедуп и сортирует", () => {
    expect(normalizeLengths([3000, 2780, 3000, -5, NaN, null, undefined])).toEqual([2780, 3000]);
  });

  it("пусто — пустой список", () => {
    expect(normalizeLengths([])).toEqual([]);
    expect(normalizeLengths([null, undefined])).toEqual([]);
  });
});

describe("productLengths", () => {
  it("возвращает нормальные длины из канонического реестра по возрастанию", () => {
    expect(
      productLengths({
        lengths: [length(3000), length(2780), length(2780, 2830)],
      }),
    ).toEqual([2780, 3000]);
  });
});

describe("primaryLength", () => {
  it("явный флаг записи реестра задаёт основную длину", () => {
    expect(primaryLength({ lengths: [length(2780), length(3500, null, true)] })).toBe(3500);
  });

  it("без явного флага берёт первую нормальную длину по возрастанию", () => {
    expect(primaryLength({ lengths: [length(3500), length(2780)] })).toBe(2780);
  });

  it("пустой реестр не создаёт основную длину", () => {
    expect(primaryLength({ lengths: [] })).toBeNull();
  });
});

describe("effectiveRawLength", () => {
  it("без явной сырьевой длины использует нормальную", () => {
    expect(effectiveRawLength(length(2700))).toBe(2700);
  });

  it("явная сырьевая длина имеет приоритет", () => {
    expect(effectiveRawLength(length(2700, 2750))).toBe(2750);
  });
});

describe("entryForLength / effectiveForLength", () => {
  const dict: QuantityPerHangerDict = {
    "2780": { auto: 72, manual: 60 },
    "3000": { auto: null, manual: 55 },
    "3500": { auto: null, manual: null },
  };

  it("режим auto — авто-значение записи", () => {
    expect(effectiveForLength(dict, 2780, "auto")).toEqual({ value: 72, source: "auto" });
    expect(effectiveForLength(dict, 3000, "auto")).toEqual({ value: null, source: "auto" });
  });

  it("режим manual — ручное значение записи", () => {
    expect(effectiveForLength(dict, 2780, "manual")).toEqual({ value: 60, source: "manual" });
    expect(effectiveForLength(dict, 3000, "manual")).toEqual({ value: 55, source: "manual" });
  });

  it("нет записи — значения нет, источник остаётся выбранным режимом", () => {
    expect(effectiveForLength(dict, 9999, "auto")).toEqual({ value: null, source: "auto" });
    expect(effectiveForLength(null, 2780, "manual")).toEqual({ value: null, source: "manual" });
    expect(entryForLength(null, 2780)).toBeNull();
  });
});

describe("primaryHangerValue", () => {
  it("в auto-режиме возвращает авто-значение основной нормальной длины", () => {
    const product = {
      lengths: [length(2780, null, true), length(3000)],
      hanger_mode: "auto" as const,
      quantity_per_hanger: {
        "2780": { auto: 72, manual: 60 },
        "3000": { auto: null, manual: 55 },
      } as QuantityPerHangerDict,
    };
    expect(primaryHangerValue(product)).toEqual({ lengthMm: 2780, value: 72, source: "auto" });
  });

  it("в manual-режиме возвращает ручное N по основной нормальной длине", () => {
    const product = {
      lengths: [length(2780, null, true)],
      hanger_mode: "manual" as const,
      quantity_per_hanger: {
        "2780": { auto: 72, manual: 40 },
      } as QuantityPerHangerDict,
    };
    expect(primaryHangerValue(product)).toEqual({ lengthMm: 2780, value: 40, source: "manual" });
  });

  it("ручное значение null не заменяется устаревшим auto", () => {
    const product = {
      lengths: [length(2780)],
      hanger_mode: "manual" as const,
      quantity_per_hanger: {
        "2780": { auto: 72, manual: null },
      } as QuantityPerHangerDict,
    };
    expect(primaryHangerValue(product)).toBeNull();
  });

  it("пустой реестр или словарь не создаёт значение", () => {
    expect(primaryHangerValue({ lengths: [], quantity_per_hanger: null })).toBeNull();
    expect(
      primaryHangerValue({ lengths: [length(2780)], quantity_per_hanger: null }),
    ).toBeNull();
  });
});

describe("manualByLength", () => {
  it("оставляет только непустые ручные значения", () => {
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

  it("length и отсутствующее состояние — не листы", () => {
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

  it("выбранный null остаётся отсутствующим значением", () => {
    expect(effectiveForMode({ auto: null, manual: 5 }, "auto")).toEqual({ value: null, source: "auto" });
    expect(effectiveForMode({ auto: 2, manual: null }, "manual")).toEqual({ value: null, source: "manual" });
    expect(effectiveForMode(null, "manual")).toEqual({ value: null, source: "manual" });
  });
});

describe("sheetHangerEntry", () => {
  it("возвращает единственную запись словаря листа", () => {
    expect(sheetHangerEntry({ "3000": { auto: 2, manual: null } })).toEqual({ auto: 2, manual: null });
  });

  it("пустой или отсутствующий словарь не создаёт запись", () => {
    expect(sheetHangerEntry({})).toBeNull();
    expect(sheetHangerEntry(null)).toBeNull();
    expect(sheetHangerEntry(undefined)).toBeNull();
  });
});
