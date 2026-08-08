import { describe, expect, it } from "vitest";

import type { Product } from "@/shared/api/products";
import type { HangerCalcResult, HangerSettings } from "@/shared/api/hangerCalc";
import {
  buildCalcItems,
  buildHangerCalcRows,
  incompatibilityReason,
  resultsToCalcMap,
  type CalcMap,
} from "./hangerCalcRows";

const SETTINGS: HangerSettings = {
  area_limit_m2: 13,
  rod_length_mm: 1450,
  gap_mm: 20,
  rod_count: 2,
};

function makeProduct(overrides: Partial<Product>): Product {
  return {
    id: 1,
    sku: "ЮП-100",
    code: null,
    name: "Профиль",
    type: "component",
    unit: "шт",
    is_active: true,
    notes: null,
    profile_type: null,
    alloy: null,
    color: null,
    anod_type: null,
    length_mm: null,
    weight_per_meter: null,
    perimeter_mm: null,
    mount_width_mm: null,
    quantity_per_hanger: null,
    cross_section: null,
    photo_thumb: null,
    photo_full: null,
    source: null,
    is_catalog_item: false,
    is_paired_profile: false,
    skip_shot_blast: false,
    dimension_state: "length",
    aliases: [],
    lengths_mm: [],
    processing_flags: [],
    is_laminated: false,
    ...overrides,
  };
}

function makeResult(overrides: Partial<HangerCalcResult>): HangerCalcResult {
  return {
    by_area: 72,
    by_size: 72,
    total: 72,
    limiter: "area",
    area_m2: 0.17976,
    is_calculable: true,
    ...overrides,
  };
}

describe("incompatibilityReason", () => {
  it("габарит + зазор > длина клюшки — причина", () => {
    expect(incompatibilityReason(1440, SETTINGS)).toContain("1440");
  });

  it("влезает — null", () => {
    expect(incompatibilityReason(19.35, SETTINGS)).toBeNull();
    expect(incompatibilityReason(1430, SETTINGS)).toBeNull();
  });

  it("нет габарита — null", () => {
    expect(incompatibilityReason(null, SETTINGS)).toBeNull();
  });
});

describe("buildCalcItems", () => {
  it("авто-артикул — по item'у на каждую длину, refs в том же порядке", () => {
    const product = makeProduct({
      id: 7,
      perimeter_mm: 64.2,
      mount_width_mm: 19.35,
      lengths_mm: [3000, 2780],
    });
    const { items, refs, incompatible } = buildCalcItems([product], SETTINGS);
    expect(items).toEqual([
      { perimeter_mm: 64.2, mount_width_mm: 19.35, length_mm: 2780 },
      { perimeter_mm: 64.2, mount_width_mm: 19.35, length_mm: 3000 },
    ]);
    expect(refs).toEqual([
      { productId: 7, lengthMm: 2780 },
      { productId: 7, lengthMm: 3000 },
    ]);
    expect(incompatible.size).toBe(0);
  });

  it("ручной артикул (нет периметра/габарита) не отправляется", () => {
    const manual = makeProduct({ id: 8, lengths_mm: [2780] });
    const { items, incompatible } = buildCalcItems([manual], SETTINGS);
    expect(items).toEqual([]);
    expect(incompatible.size).toBe(0);
  });

  it("несовместимый габарит помечается и не рвёт batch", () => {
    const bad = makeProduct({
      id: 9,
      perimeter_mm: 100,
      mount_width_mm: 1440,
      lengths_mm: [2780],
    });
    const good = makeProduct({
      id: 10,
      perimeter_mm: 64.2,
      mount_width_mm: 19.35,
      lengths_mm: [2780],
    });
    const { items, refs, incompatible } = buildCalcItems([bad, good], SETTINGS);
    expect(incompatible.get(9)).toBeTruthy();
    expect(items).toHaveLength(1);
    expect(refs[0].productId).toBe(10);
  });
});

describe("resultsToCalcMap", () => {
  it("раскладывает результаты по productId → lengthKey по порядку items", () => {
    const refs = [
      { productId: 1, lengthMm: 2780 },
      { productId: 1, lengthMm: 3000 },
      { productId: 2, lengthMm: 2780 },
    ];
    const results = [
      makeResult({ total: 72 }),
      makeResult({ total: 65 }),
      makeResult({ total: 60 }),
    ];
    const map = resultsToCalcMap(refs, results);
    expect(map.get(1)?.get("2780")?.total).toBe(72);
    expect(map.get(1)?.get("3000")?.total).toBe(65);
    expect(map.get(2)?.get("2780")?.total).toBe(60);
  });

  it("короткий список результатов не рвёт раскладку", () => {
    const refs = [{ productId: 1, lengthMm: 2780 }, { productId: 2, lengthMm: 2780 }];
    const map = resultsToCalcMap(refs, [makeResult({})]);
    expect(map.get(1)?.size).toBe(1);
    expect(map.get(2)).toBeUndefined();
  });
});

describe("buildHangerCalcRows", () => {
  it("авто-артикул: разбивка по основной (минимальной) длине", () => {
    const product = makeProduct({
      id: 1,
      perimeter_mm: 64.2,
      mount_width_mm: 19.35,
      lengths_mm: [3000, 2780],
      quantity_per_hanger: {
        "2780": { auto: 72, manual: 60 },
        "3000": { auto: 65, manual: null },
      },
    });
    const calcMap: CalcMap = new Map([
      [1, new Map([["2780", makeResult({ total: 72, limiter: "area" })]])],
    ]);
    const [row] = buildHangerCalcRows([product], calcMap, new Map());
    expect(row.auto).toBe(true);
    expect(row.primaryLength).toBe(2780);
    expect(row.total).toBe(72);
    expect(row.limiter).toBe("area");
    expect(row.areaM2).toBeCloseTo(0.17976);
    expect(row.incompatibleReason).toBeNull();
  });

  it("ручной артикул: разбивки нет, итог — ручное значение основной длины", () => {
    const product = makeProduct({
      id: 2,
      lengths_mm: [2780],
      quantity_per_hanger: { "2780": { auto: null, manual: 40 } },
    });
    const [row] = buildHangerCalcRows([product], new Map(), new Map());
    expect(row.auto).toBe(false);
    expect(row.primaryResult).toBeNull();
    expect(row.total).toBe(40);
  });

  it("ручной артикул с устаревшим auto: итог — только manual (#64)", () => {
    const product = makeProduct({
      id: 6,
      lengths_mm: [2780],
      // Stale auto from previous auto-mode — should NOT affect total.
      quantity_per_hanger: { "2780": { auto: 72, manual: 40 } },
    });
    const [row] = buildHangerCalcRows([product], new Map(), new Map());
    expect(row.auto).toBe(false);
    expect(row.total).toBe(40);
  });

  it("несовместимый артикул помечается причиной, итоги не считаются", () => {
    const product = makeProduct({
      id: 3,
      perimeter_mm: 100,
      mount_width_mm: 1440,
      lengths_mm: [2780],
    });
    const incompatible = new Map([[3, "габарит не влезает"]]);
    const [row] = buildHangerCalcRows([product], new Map(), incompatible);
    expect(row.auto).toBe(true);
    expect(row.incompatibleReason).toBe("габарит не влезает");
    expect(row.total).toBeNull();
    expect(row.limiter).toBeNull();
  });

  it("авто-артикул без результата (нет длин) — итог null", () => {
    const product = makeProduct({ id: 4, perimeter_mm: 64.2, mount_width_mm: 19.35, lengths_mm: [] });
    const [row] = buildHangerCalcRows([product], new Map(), new Map());
    expect(row.auto).toBe(true);
    expect(row.primaryLength).toBeNull();
    expect(row.total).toBeNull();
  });

  it("нерасчётный результат (is_calculable=false) — итог null", () => {
    const product = makeProduct({
      id: 5,
      perimeter_mm: 64.2,
      mount_width_mm: 19.35,
      lengths_mm: [2780],
    });
    const calcMap: CalcMap = new Map([
      [5, new Map([["2780", makeResult({ is_calculable: false, total: null, limiter: null })]])],
    ]);
    const [row] = buildHangerCalcRows([product], calcMap, new Map());
    expect(row.total).toBeNull();
    expect(row.primaryResult?.is_calculable).toBe(false);
  });
});
