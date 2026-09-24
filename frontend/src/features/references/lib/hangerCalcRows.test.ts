import { describe, expect, it } from "vitest";

import type { Product, ProductLength, ProductPairCatalogEntry } from "@/shared/api/products";
import type { HangerCalcResult, HangerSettings } from "@/shared/api/hangerCalc";
import {
  buildCalcItems,
  buildHangerCalcRows,
  buildPairedCalcItems,
  buildPairedHangerCalcRows,
  incompatibilityReason,
  formatPairedLengthLabel,
  pairedIncompatibilityReason,
  resolvePairs,
  resultsToCalcMap,
  resultsToPairedCalcMap,
  type CalcMap,
  type PairedPair,
  rowSearchValues,
} from "./hangerCalcRows";

const SETTINGS: HangerSettings = {
  area_limit_m2: 13,
  rod_length_mm: 1450,
  gap_mm: 20,
  rod_count: 2,
};

const productLength = (
  length_mm: number,
  raw_length_mm: number | null = null,
  is_primary = false,
): ProductLength => ({ length_mm, raw_length_mm, is_primary });

const productLengths = (...values: number[]): ProductLength[] =>
  values.map((value) => productLength(value));

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
    weight_per_meter: null,
    perimeter_mm: null,
    mount_width_mm: null,
    quantity_per_hanger: null,
    hanger_mode: "auto",
    cross_section: null,
    photo_thumb: null,
    photo_full: null,
    source: null,
    is_catalog_item: false,
    is_paired_profile: false,
    skip_shot_blast: false,
    dimension_state: "length",
    aliases: [],
    lengths: [],
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

/** Элемент pairs-API (каталог всех пар) для resolvePairs. */
function makePairEntry(overrides: Partial<ProductPairCatalogEntry>): ProductPairCatalogEntry {
  return {
    id: 7,
    product_a_id: 1,
    product_b_id: 2,
    lengths: [3000],
    quantity_per_hanger: {},
    ...overrides,
  };
}

/** Разрешённая пара для build*-функций. */
function makePair(
  overrides: Partial<PairedPair> & Pick<PairedPair, "productA" | "productB">,
): PairedPair {
  return {
    pairId: 7,
    lengths: [3000],
    manualPerLength: {},
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
      lengths: [productLength(3000), productLength(2780, null, true)],
    });
    const { items, refs, incompatible } = buildCalcItems([product], SETTINGS);
    expect(items).toEqual([
      { perimeter_mm: 64.2, mount_width_mm: 19.35, length_mm: 3000 },
      { perimeter_mm: 64.2, mount_width_mm: 19.35, length_mm: 2780 },
    ]);
    expect(refs).toEqual([
      { productId: 7, lengthMm: 3000 },
      { productId: 7, lengthMm: 2780 },
    ]);
    expect(incompatible.size).toBe(0);
  });

  it("в формулу уходит effective raw, а ref остаётся ключом нормальной длины", () => {
    const product = makeProduct({
      id: 17,
      perimeter_mm: 64.2,
      mount_width_mm: 19.35,
      lengths: [productLength(2700, 2750, true), productLength(3000)],
    });
    const { items, refs } = buildCalcItems([product], SETTINGS);
    expect(items.map((item) => item.length_mm)).toEqual([2750, 3000]);
    expect(refs).toEqual([
      { productId: 17, lengthMm: 2700 },
      { productId: 17, lengthMm: 3000 },
    ]);
  });
  it("ручной артикул (нет периметра/габарита) не отправляется", () => {
    const manual = makeProduct({ id: 8, lengths: productLengths(2780) });
    const { items, incompatible } = buildCalcItems([manual], SETTINGS);
    expect(items).toEqual([]);
    expect(incompatible.size).toBe(0);
  });

  it("артикул в ручном режиме (даже с полями) не отправляется (#127)", () => {
    const manual = makeProduct({
      id: 16,
      hanger_mode: "manual",
      lengths: productLengths(2780),
      mount_width_mm: 19.35,
    });
    const { items, incompatible } = buildCalcItems([manual], SETTINGS);
    expect(items).toEqual([]);
    expect(incompatible.size).toBe(0);
  });

  it("несовместимый габарит помечается и не рвёт batch", () => {
    const bad = makeProduct({
      id: 9,
      perimeter_mm: 100,
      mount_width_mm: 1440,
      lengths: productLengths(2780),
    });
    const good = makeProduct({
      id: 10,
      perimeter_mm: 64.2,
      mount_width_mm: 19.35,
      lengths: productLengths(2780),
    });
    const { items, refs, incompatible } = buildCalcItems([bad, good], SETTINGS);
    expect(incompatible.get(9)).toBeTruthy();
    expect(items).toHaveLength(1);
    expect(refs[0].productId).toBe(10);
  });

  // ─── Листы 2D/3D (#126) ───────────────────────────────────────────────

  it("лист 2D в авто-режиме — один item kind='sheet' по осям полотна", () => {
    const sheet = makeProduct({
      id: 11,
      dimension_state: "area",
      hanger_mode: "auto",
      dimensions: { length_mm: 3000, width_mm: 1500 },
    });
    const { items, refs, incompatible } = buildCalcItems([sheet], SETTINGS);
    expect(items).toEqual([
      { kind: "sheet", perimeter_mm: null, mount_width_mm: null, length_mm: 3000, width_mm: 1500, height_mm: null },
    ]);
    expect(refs).toEqual([{ productId: 11, lengthMm: 3000 }]);
    expect(incompatible.size).toBe(0);
  });

  it("лист 3D — height_mm уходит в item, у 2D — всегда null", () => {
    const volume = makeProduct({
      id: 12,
      dimension_state: "volume",
      dimensions: { length_mm: 2000, width_mm: 1000, height_mm: 300 },
    });
    const area = makeProduct({
      id: 13,
      dimension_state: "area",
      dimensions: { length_mm: 2000, width_mm: 1000, height_mm: 300 },
    });
    const { items } = buildCalcItems([volume, area], SETTINGS);
    expect(items[0].height_mm).toBe(300);
    expect(items[1].height_mm).toBeNull();
  });

  it("лист в ручном режиме не отправляется в расчёт", () => {
    const sheet = makeProduct({
      id: 14,
      dimension_state: "area",
      hanger_mode: "manual",
      dimensions: { length_mm: 3000, width_mm: 1500 },
    });
    const { items, incompatible } = buildCalcItems([sheet], SETTINGS);
    expect(items).toEqual([]);
    expect(incompatible.size).toBe(0);
  });

  it("лист без длины полотна не отправляется", () => {
    const sheet = makeProduct({
      id: 15,
      dimension_state: "area",
      dimensions: { width_mm: 1500 },
    });
    const { items } = buildCalcItems([sheet], SETTINGS);
    expect(items).toEqual([]);
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
      lengths: [productLength(3000), productLength(2780, null, true)],
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

  it("строка сохраняет отдельную сырьевую длину для каждой нормальной", () => {
    const product = makeProduct({
      lengths: [productLength(2700, 2750, true), productLength(3000, 3050)],
    });
    const [row] = buildHangerCalcRows([product], new Map(), new Map());
    expect(row.lengths).toEqual([2700, 3000]);
    expect(row.product.lengths).toEqual([
      productLength(2700, 2750, true),
      productLength(3000, 3050),
    ]);
  });

  it("явный is_primary в записи реестра задаёт разбивку", () => {
    const product = makeProduct({
      id: 1,
      perimeter_mm: 64.2,
      mount_width_mm: 19.35,
      lengths: [productLength(2780), productLength(3000, null, true)],
      quantity_per_hanger: {
        "2780": { auto: 72, manual: 60 },
        "3000": { auto: 65, manual: null },
      },
    });
    const calcMap: CalcMap = new Map([
      [1, new Map([["3000", makeResult({ total: 65, limiter: "size" })]])],
    ]);
    const [row] = buildHangerCalcRows([product], calcMap, new Map());
    expect(row.primaryLength).toBe(3000);
    expect(row.total).toBe(65);
    expect(row.limiter).toBe("size");
  });

  it("ручной артикул: разбивки нет, итог — ручное значение основной длины", () => {
    const product = makeProduct({
      id: 2,
      hanger_mode: "manual",
      lengths: productLengths(2780),
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
      hanger_mode: "manual",
      lengths: productLengths(2780),
      // Stale auto from previous auto-mode — should NOT affect total.
      quantity_per_hanger: { "2780": { auto: 72, manual: 40 } },
    });
    const [row] = buildHangerCalcRows([product], new Map(), new Map());
    expect(row.auto).toBe(false);
    expect(row.total).toBe(40);
  });

  it("артикул в ручном режиме с заполненными полями: итог — только manual (#127)", () => {
    const product = makeProduct({
      id: 7,
      hanger_mode: "manual",
      perimeter_mm: 64.2,
      mount_width_mm: 19.35,
      lengths: productLengths(2780),
      quantity_per_hanger: { "2780": { auto: 72, manual: 40 } },
    });
    const [row] = buildHangerCalcRows([product], new Map(), new Map());
    expect(row.auto).toBe(false);
    expect(row.primaryResult).toBeNull();
    expect(row.total).toBe(40);
  });

  it("несовместимый артикул помечается причиной, итоги не считаются", () => {
    const product = makeProduct({
      id: 3,
      perimeter_mm: 100,
      mount_width_mm: 1440,
      lengths: productLengths(2780),
    });
    const incompatible = new Map([[3, "габарит не влезает"]]);
    const [row] = buildHangerCalcRows([product], new Map(), incompatible);
    expect(row.auto).toBe(true);
    expect(row.incompatibleReason).toBe("габарит не влезает");
    expect(row.total).toBeNull();
    expect(row.limiter).toBeNull();
  });

  it("авто-артикул без результата (нет длин) — итог null", () => {
    const product = makeProduct({ id: 4, perimeter_mm: 64.2, mount_width_mm: 19.35, lengths: [] });
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
      lengths: productLengths(2780),
    });
    const calcMap: CalcMap = new Map([
      [5, new Map([["2780", makeResult({ is_calculable: false, total: null, limiter: null })]])],
    ]);
    const [row] = buildHangerCalcRows([product], calcMap, new Map());
    expect(row.total).toBeNull();
    expect(row.primaryResult?.is_calculable).toBe(false);
  });

  // ─── Листы 2D/3D (#126) ───────────────────────────────────────────────

  it("лист в авто-режиме: итог — результат расчёта по длине полотна", () => {
    const product = makeProduct({
      id: 20,
      dimension_state: "area",
      hanger_mode: "auto",
      dimensions: { length_mm: 3000, width_mm: 1500 },
      quantity_per_hanger: { "3000": { auto: 2, manual: 5 } },
    });
    const calcMap: CalcMap = new Map([
      [20, new Map([["3000", makeResult({ total: 2, limiter: "area" })]])],
    ]);
    const [row] = buildHangerCalcRows([product], calcMap, new Map());
    expect(row.auto).toBe(true);
    expect(row.primaryLength).toBe(3000);
    expect(row.lengths).toEqual([3000]);
    expect(row.total).toBe(2);
    expect(row.primaryResult?.total).toBe(2);
  });

  it("лист в ручном режиме: итог — только manual единственной записи", () => {
    const product = makeProduct({
      id: 21,
      dimension_state: "area",
      hanger_mode: "manual",
      dimensions: { length_mm: 3000, width_mm: 1500 },
      quantity_per_hanger: { "3000": { auto: 2, manual: 5 } },
    });
    const [row] = buildHangerCalcRows([product], new Map(), new Map());
    expect(row.auto).toBe(false);
    expect(row.primaryResult).toBeNull();
    expect(row.total).toBe(5);
  });

  it("лист без результата (нерасчётный) — итог null, причина в primaryResult", () => {
    const product = makeProduct({
      id: 22,
      dimension_state: "area",
      dimensions: { length_mm: 4000, width_mm: 2000 },
    });
    const calcMap: CalcMap = new Map([
      [22, new Map([["4000", makeResult({ is_calculable: false, total: null, limiter: null, reason: "Полотно 4000×2000 мм больше листа 3000×1500 мм" })]])],
    ]);
    const [row] = buildHangerCalcRows([product], calcMap, new Map());
    expect(row.auto).toBe(true);
    expect(row.total).toBeNull();
    expect(row.primaryResult?.reason).toContain("3000×1500");
  });
});

// ─── Пары из pairs-API (#150) ────────────────────────────────────────────────

describe("pairedIncompatibilityReason", () => {
  it("сумма габаритов + зазоры > общая длина клюшек — причина", () => {
    // 1500 + 1500 + 40 = 3040 > 2900
    expect(pairedIncompatibilityReason(1500, 1500, SETTINGS)).toContain("2900");
  });

  it("влезает — null", () => {
    expect(pairedIncompatibilityReason(19.35, 19.35, SETTINGS)).toBeNull();
    // 1430 + 1430 + 40 = 2900 — не строго больше, допустимо
    expect(pairedIncompatibilityReason(1430, 1430, SETTINGS)).toBeNull();
  });

  it("нет габаритов — null", () => {
    expect(pairedIncompatibilityReason(null, 19.35, SETTINGS)).toBeNull();
    expect(pairedIncompatibilityReason(null, null, SETTINGS)).toBeNull();
  });
});

describe("resolvePairs", () => {
  function product(id: number, sku: string): Product {
    return makeProduct({ id, sku, lengths: productLengths(2780, 3000) });
  }

  it("сопоставляет пару из pairs-API с двумя артикулами", () => {
    const entry = makePairEntry({
      id: 7,
      lengths: [3000],
      quantity_per_hanger: { "3000": { auto: 30, manual: 25 } },
    });
    const pairs = resolvePairs([entry], [product(1, "ЮП-A"), product(2, "ЮП-B")]);
    expect(pairs).toHaveLength(1);
    expect(pairs[0]).toMatchObject({
      pairId: 7,
      lengths: [3000],
      manualPerLength: { "3000": 25 },
    });
    expect(pairs[0].productA.sku).toBe("ЮП-A");
    expect(pairs[0].productB.sku).toBe("ЮП-B");
  });

  it("пропускает пару, чей артикул не в загруженном наборе", () => {
    const entry = makePairEntry({ product_b_id: 99 });
    expect(resolvePairs([entry], [product(1, "ЮП-A")])).toHaveLength(0);
  });

  it("пара с пустым пересечением длин (lengths: []) не даёт строку и не роняет список", () => {
    const entry = makePairEntry({
      lengths: [],
      quantity_per_hanger: {},
    });
    expect(resolvePairs([entry], [product(1, "ЮП-A"), product(2, "ЮП-B")])).toHaveLength(0);
  });
});

describe("buildPairedCalcItems", () => {
  const autoA = () => makeProduct({ id: 1, sku: "ЮП-A", perimeter_mm: 64.2, mount_width_mm: 19.35, lengths: productLengths(2780, 3000) });
  const autoB = () => makeProduct({ id: 2, sku: "ЮП-B", perimeter_mm: 64.2, mount_width_mm: 19.35, lengths: productLengths(3000, 3500) });
  const manualModeB = () => makeProduct({ id: 2, sku: "ЮП-B", hanger_mode: "manual", perimeter_mm: 64.2, mount_width_mm: 19.35, lengths: productLengths(3000, 3500) });
  const noDataB = () => makeProduct({ id: 2, sku: "ЮП-B", lengths: productLengths(3000, 3500) });
  const pair = (a: Product, b: Product, lengths = [3000]) => makePair({ productA: a, productB: b, lengths });

  it("авто-пара: item создаётся для общей нормальной длины", () => {
    const { items, refs, incompatible } = buildPairedCalcItems(
      [pair(autoA(), autoB(), [3000])],
      SETTINGS,
    );
    expect(items).toEqual([
      {
        perimeter_a_mm: 64.2,
        mount_width_a_mm: 19.35,
        perimeter_b_mm: 64.2,
        mount_width_b_mm: 19.35,
        length_mm: 3000,
      },
    ]);
    expect(refs).toEqual([{ pairId: 7, lengthMm: 3000 }]);
    expect(incompatible.size).toBe(0);
  });

  it("пара отправляет одинаковую effective raw, но результат остаётся keyed по нормальной", () => {
    const a = autoA();
    const b = autoB();
    a.lengths = [productLength(3000, 3050, true)];
    b.lengths = [productLength(3000, 3050, true)];
    const { items, refs } = buildPairedCalcItems([pair(a, b, [3000])], SETTINGS);
    expect(items[0]?.length_mm).toBe(3050);
    expect(refs).toEqual([{ pairId: 7, lengthMm: 3000 }]);
  });

  it("пара с одним ручным артикулом (hanger_mode=manual) не считается — режим пары ручной", () => {
    const { items, incompatible } = buildPairedCalcItems([pair(autoA(), manualModeB())], SETTINGS);
    expect(items).toEqual([]);
    expect(incompatible.size).toBe(0);
  });

  it("пара без данных движка (нет периметра/габарита) не отправляется", () => {
    const { items } = buildPairedCalcItems([pair(autoA(), noDataB())], SETTINGS);
    expect(items).toEqual([]);
  });

  it("несовместимая пара помечается и не рвёт batch", () => {
    const wide = (id: number, sku: string) =>
      makeProduct({ id, sku, perimeter_mm: 100, mount_width_mm: 1500, lengths: productLengths(3000) });
    const { items, refs, incompatible } = buildPairedCalcItems([
      pair(wide(3, "ЮП-WIDE-A"), wide(4, "ЮП-WIDE-B")),
      pair(autoA(), autoB()),
    ], SETTINGS);
    expect(incompatible.get(7)).toBeTruthy();
    expect(items).toHaveLength(1);
    expect(refs[0].lengthMm).toBe(3000);
  });
});

describe("resultsToPairedCalcMap", () => {
  it("раскладывает результаты по pairId → lengthKey", () => {
    const refs = [
      { pairId: 7, lengthMm: 2780 },
      { pairId: 7, lengthMm: 3000 },
      { pairId: 8, lengthMm: 2780 },
    ];
    const map = resultsToPairedCalcMap(refs, [
      makeResult({ total: 36 }),
      makeResult({ total: 30 }),
      makeResult({ total: 40 }),
    ]);
    expect(map.get(7)?.get("2780")?.total).toBe(36);
    expect(map.get(7)?.get("3000")?.total).toBe(30);
    expect(map.get(8)?.get("2780")?.total).toBe(40);
  });
});

describe("buildPairedHangerCalcRows", () => {
  it("авто-пара: разбивка по первой длине пары, совместный итог", () => {
    const pair = makePair({
      productA: makeProduct({ id: 1, sku: "ЮП-A", perimeter_mm: 64.2, mount_width_mm: 19.35, lengths: productLengths(2780, 3000) }),
      productB: makeProduct({ id: 2, sku: "ЮП-B", perimeter_mm: 64.2, mount_width_mm: 19.35, lengths: productLengths(3000, 3500) }),
      lengths: [3000],
    });
    const calcMap = new Map([[7, new Map([["3000", makeResult({ total: 30, limiter: "area" })]])]]);
    const [row] = buildPairedHangerCalcRows([pair], calcMap, new Map());
    expect(row.kind).toBe("paired");
    expect(row.label).toBe("ЮП-A + ЮП-B");
    expect(row.auto).toBe(true);
    expect(row.primaryLength).toBe(3000);
    expect(row.lengths).toEqual([3000]);
    expect(row.total).toBe(30);
    expect(row.limiter).toBe("area");
    expect(row.primaryResult?.by_area).toBe(72);
    // Суммы пары идут в формулы совместного расчёта (Feature Envy fix).
    expect(row.perimeterSum).toBe(128.4);
    expect(row.widthSum).toBe(38.7);
  });

  it("ручная пара: итог — ручное N из словаря пары на основной длине", () => {
    const pair = makePair({
      productA: makeProduct({ id: 1, sku: "ЮП-A", lengths: productLengths(2780) }),
      productB: makeProduct({ id: 2, sku: "ЮП-B", hanger_mode: "manual", lengths: productLengths(2780) }),
      lengths: [2780],
      manualPerLength: { "2780": 40 },
    });
    const [row] = buildPairedHangerCalcRows([pair], new Map(), new Map());
    expect(row.auto).toBe(false);
    expect(row.primaryResult).toBeNull();
    expect(row.total).toBe(40);
    expect(row.perimeterSum).toBeNull();
    expect(row.widthSum).toBeNull();
  });

  it("ручная пара без ручного N на длине — итог null", () => {
    const pair = makePair({
      productA: makeProduct({ id: 1, sku: "ЮП-A", lengths: productLengths(2780) }),
      productB: makeProduct({ id: 2, sku: "ЮП-B", hanger_mode: "manual", lengths: productLengths(2780) }),
      lengths: [2780],
      manualPerLength: {},
    });
    const [row] = buildPairedHangerCalcRows([pair], new Map(), new Map());
    expect(row.auto).toBe(false);
    expect(row.total).toBeNull();
  });

  it("несовместимая пара помечается причиной, итоги не считаются", () => {
    const pair = makePair({
      productA: makeProduct({ id: 1, sku: "ЮП-A", perimeter_mm: 100, mount_width_mm: 1500, lengths: productLengths(3000) }),
      productB: makeProduct({ id: 2, sku: "ЮП-B", perimeter_mm: 100, mount_width_mm: 1500, lengths: productLengths(3000) }),
      lengths: [3000],
      manualPerLength: { "3000": 10 },
    });
    const incompatible = new Map([[7, "пара не влезает"]]);
    const [row] = buildPairedHangerCalcRows([pair], new Map(), incompatible);
    expect(row.auto).toBe(true);
    expect(row.incompatibleReason).toBe("пара не влезает");
    expect(row.total).toBeNull();
  });

  it("авто-пара без длин пары — итог null", () => {
    const pair = makePair({
      productA: makeProduct({ id: 1, sku: "ЮП-A", perimeter_mm: 64.2, mount_width_mm: 19.35 }),
      productB: makeProduct({ id: 2, sku: "ЮП-B", perimeter_mm: 64.2, mount_width_mm: 19.35 }),
      lengths: [],
    });
    const [row] = buildPairedHangerCalcRows([pair], new Map(), new Map());
    expect(row.auto).toBe(true);
    expect(row.primaryLength).toBeNull();
    expect(row.total).toBeNull();
  });
});

describe("rowSearchValues", () => {
  it("одиночная строка ищется по SKU, normal и explicit raw", () => {
    const product = makeProduct({ lengths: [productLength(2700, 2750, true)] });
    const [row] = buildHangerCalcRows([product], new Map(), new Map());

    expect(rowSearchValues(row)).toEqual(
      expect.arrayContaining(["ЮП-100", "2700", "2750"]),
    );
  });

  it("при null raw ищет normal как effective raw", () => {
    const product = makeProduct({ lengths: [productLength(2700, null, true)] });
    const [row] = buildHangerCalcRows([product], new Map(), new Map());

    expect(rowSearchValues(row)).toEqual(expect.arrayContaining(["2700"]));
  });

  it("парная строка ищется по label и обеим normal/raw длинам", () => {
    const pair = makePair({
      productA: makeProduct({
        id: 1,
        sku: "ЮП-A",
        lengths: [productLength(2700, null, true)],
      }),
      productB: makeProduct({
        id: 2,
        sku: "ЮП-B",
        lengths: [productLength(3000, 3050, true)],
      }),
      lengths: [2700, 3000],
    });
    const [row] = buildPairedHangerCalcRows([pair], new Map(), new Map());

    expect(rowSearchValues(row)).toEqual(
      expect.arrayContaining(["ЮП-A + ЮП-B", "2700", "3000", "3050"]),
    );
  });
});

describe("formatPairedLengthLabel", () => {
  it("при равных normal и raw явно показывает сырьё", () => {
    const label = formatPairedLengthLabel(2700, 2700, 2700);

    expect(label).toContain("2700");
    expect(label).toContain("сырьё 2700");
  });

  it("показывает разные raw обеих сторон", () => {
    const label = formatPairedLengthLabel(3000, 2750, 3050);

    expect(label).toContain("2750");
    expect(label).toContain("3050");
  });
});
