import { describe, expect, it } from "vitest";

import type { QuantityPerHangerDict } from "@/shared/api/products";
import {
  effectiveForLength,
  effectiveValue,
  entryForLength,
  isHangerAutoMode,
  lengthKey,
  manualByLength,
  primaryHangerValue,
  productLengths,
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

describe("productLengths", () => {
  it("мержит lengths_mm и legacy length_mm, сортирует по возрастанию, убирает дубли и мусор", () => {
    expect(
      productLengths({ lengths_mm: [3000, 2780, 3000, -5, NaN], length_mm: 2500 }),
    ).toEqual([2500, 2780, 3000]);
  });

  it("пусто — пустой список", () => {
    expect(productLengths({ lengths_mm: [], length_mm: null })).toEqual([]);
  });
});

describe("effectiveValue / entryForLength / effectiveForLength", () => {
  const dict: QuantityPerHangerDict = {
    "2780": { auto: 72, manual: 60 },
    "3000": { auto: null, manual: 55 },
    "3500": { auto: null, manual: null },
  };

  it("приоритет авто > ручное", () => {
    expect(effectiveValue({ auto: 72, manual: 60 })).toEqual({ value: 72, source: "auto" });
  });

  it("нет авто — берётся ручное", () => {
    expect(effectiveValue({ auto: null, manual: 55 })).toEqual({ value: 55, source: "manual" });
  });

  it("оба null — значения нет", () => {
    expect(effectiveValue({ auto: null, manual: null })).toEqual({ value: null, source: null });
    expect(effectiveValue(null)).toEqual({ value: null, source: null });
  });

  it("lookup по длине через lengthKey", () => {
    expect(effectiveForLength(dict, 2780)).toEqual({ value: 72, source: "auto" });
    expect(effectiveForLength(dict, 3000)).toEqual({ value: 55, source: "manual" });
    expect(effectiveForLength(dict, 9999)).toEqual({ value: null, source: null });
    expect(entryForLength(null, 2780)).toBeNull();
  });
});

describe("primaryHangerValue", () => {
  it("значение основной (минимальной) длины с источником", () => {
    const product = {
      lengths_mm: [3000, 2780],
      length_mm: null,
      quantity_per_hanger: {
        "2780": { auto: 72, manual: null },
        "3000": { auto: null, manual: 55 },
      } as QuantityPerHangerDict,
    };
    expect(primaryHangerValue(product)).toEqual({ lengthMm: 2780, value: 72, source: "auto" });
  });

  it("ручной артикул — ручное значение основной длины", () => {
    const product = {
      lengths_mm: [2780],
      length_mm: null,
      quantity_per_hanger: { "2780": { auto: null, manual: 40 } } as QuantityPerHangerDict,
    };
    expect(primaryHangerValue(product)).toEqual({ lengthMm: 2780, value: 40, source: "manual" });
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
