import { describe, expect, it } from "vitest";

import type { Product } from "@/shared/api/products";
import type { HangerCalcResult, HangerSettings } from "@/shared/api/hangerCalc";
import type { Techcard } from "@/shared/api/techcards";
import {
  buildCalcItems,
  buildHangerCalcRows,
  buildPairedCalcItems,
  buildPairedHangerCalcRows,
  incompatibilityReason,
  intersectLengths,
  pairedIncompatibilityReason,
  resolvePairs,
  resultsToCalcMap,
  resultsToPairedCalcMap,
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
    primary_length_mm: null,
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

function makeTechcard(overrides: Partial<Techcard>): Techcard {
  return {
    id: 100,
    product_id: null,
    version: "A",
    processing_type: "paired_processing",
    is_active: true,
    quantity_total: 2,
    quantity_a_per_item: 1,
    quantity_b_per_item: 1,
    hangers_a: null,
    hangers_b: null,
    hangers_total: null,
    product_sku: null,
    techcard_lines: [],
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

  it("авто-артикул: явная primary_length_mm задаёт разбивку (#81/#85)", () => {
    const product = makeProduct({
      id: 1,
      perimeter_mm: 64.2,
      mount_width_mm: 19.35,
      primary_length_mm: 3000,
      lengths_mm: [2780, 3000],
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

// ─── Парные техкарты (#67) ──────────────────────────────────────────────────

describe("intersectLengths", () => {
  it("общие длины — пересечение по возрастанию", () => {
    expect(intersectLengths([2780, 3000, 3500], [3000, 3500, 4000])).toEqual([3000, 3500]);
  });

  it("пустое пересечение — пустой список", () => {
    expect(intersectLengths([2780], [3000])).toEqual([]);
  });
});

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
    return makeProduct({ id, sku, lengths_mm: [2780, 3000] });
  }

  it("сопоставляет парную техкарту с двумя артикулами", () => {
    const techcard = makeTechcard({
      id: 7,
      quantity_a_per_item: 36,
      quantity_b_per_item: 36,
      techcard_lines: [
        { id: 1, component_product_id: 1, component_product_sku: "ЮП-A", quantity: 36, unit: "pcs" },
        { id: 2, component_product_id: 2, component_product_sku: "ЮП-B", quantity: 36, unit: "pcs" },
      ],
    });
    const pairs = resolvePairs([techcard], [product(1, "ЮП-A"), product(2, "ЮП-B")]);
    expect(pairs).toHaveLength(1);
    expect(pairs[0]).toMatchObject({
      techcardId: 7,
      perHanger: 36,
    });
    expect(pairs[0].productA.sku).toBe("ЮП-A");
    expect(pairs[0].productB.sku).toBe("ЮП-B");
  });

  it("пропускает пару, чей компонент не в загруженном наборе", () => {
    const techcard = makeTechcard({
      id: 7,
      techcard_lines: [
        { id: 1, component_product_id: 1, quantity: 1, unit: "pcs" },
        { id: 2, component_product_id: 99, quantity: 1, unit: "pcs" },
      ],
    });
    expect(resolvePairs([techcard], [product(1, "ЮП-A")])).toHaveLength(0);
  });

  it("пропускает стандартные техкарты и пары без линий", () => {
    const standard = makeTechcard({ id: 8, processing_type: "standart_processing" });
    const noLines = makeTechcard({ id: 9, techcard_lines: [] });
    expect(resolvePairs([standard, noLines], [product(1, "ЮП-A")])).toHaveLength(0);
  });
});

describe("buildPairedCalcItems", () => {
  const autoA = () => makeProduct({ id: 1, sku: "ЮП-A", perimeter_mm: 64.2, mount_width_mm: 19.35, lengths_mm: [2780, 3000] });
  const autoB = () => makeProduct({ id: 2, sku: "ЮП-B", perimeter_mm: 64.2, mount_width_mm: 19.35, lengths_mm: [3000, 3500] });
  const manualB = () => makeProduct({ id: 2, sku: "ЮП-B", lengths_mm: [3000, 3500] });
  const pair = (a: Product, b: Product) => ({
    techcardId: 7,
    productA: a,
    productB: b,
    perHanger: 36,
  });

  it("авто-пара: item на каждую общую длину, refs в том же порядке", () => {
    const { items, refs, incompatible } = buildPairedCalcItems([pair(autoA(), autoB())], SETTINGS);
    // Общие длины A=[2780,3000] ∩ B=[3000,3500] = [3000]
    expect(items).toEqual([{
      perimeter_a_mm: 64.2,
      mount_width_a_mm: 19.35,
      perimeter_b_mm: 64.2,
      mount_width_b_mm: 19.35,
      length_mm: 3000,
    }]);
    expect(refs).toEqual([{ techcardId: 7, lengthMm: 3000 }]);
    expect(incompatible.size).toBe(0);
  });

  it("ручная пара (не оба авто) не отправляется", () => {
    const { items, incompatible } = buildPairedCalcItems([pair(autoA(), manualB())], SETTINGS);
    expect(items).toEqual([]);
    expect(incompatible.size).toBe(0);
  });

  it("несовместимая пара помечается и не рвёт batch", () => {
    const wide = (id: number, sku: string) =>
      makeProduct({ id, sku, perimeter_mm: 100, mount_width_mm: 1500, lengths_mm: [3000] });
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
  it("раскладывает результаты по techcardId → lengthKey", () => {
    const refs = [
      { techcardId: 7, lengthMm: 2780 },
      { techcardId: 7, lengthMm: 3000 },
      { techcardId: 8, lengthMm: 2780 },
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
  it("авто-пара: разбивка по первой общей длине, совместный итог", () => {
    const pair = {
      techcardId: 7,
      productA: makeProduct({ id: 1, sku: "ЮП-A", perimeter_mm: 64.2, mount_width_mm: 19.35, lengths_mm: [2780, 3000] }),
      productB: makeProduct({ id: 2, sku: "ЮП-B", perimeter_mm: 64.2, mount_width_mm: 19.35, lengths_mm: [3000, 3500] }),
      perHanger: 36,
    };
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
  });

  it("ручная пара: разбивки нет, итог — ручное N техкарты", () => {
    const pair = {
      techcardId: 7,
      productA: makeProduct({ id: 1, sku: "ЮП-A", lengths_mm: [2780] }),
      productB: makeProduct({ id: 2, sku: "ЮП-B", lengths_mm: [2780] }),
      perHanger: 40,
    };
    const [row] = buildPairedHangerCalcRows([pair], new Map(), new Map());
    expect(row.auto).toBe(false);
    expect(row.primaryResult).toBeNull();
    expect(row.total).toBe(40);
  });

  it("несовместимая пара помечается причиной, итоги не считаются", () => {
    const pair = {
      techcardId: 7,
      productA: makeProduct({ id: 1, sku: "ЮП-A", perimeter_mm: 100, mount_width_mm: 1500, lengths_mm: [3000] }),
      productB: makeProduct({ id: 2, sku: "ЮП-B", perimeter_mm: 100, mount_width_mm: 1500, lengths_mm: [3000] }),
      perHanger: 10,
    };
    const incompatible = new Map([[7, "пара не влезает"]]);
    const [row] = buildPairedHangerCalcRows([pair], new Map(), incompatible);
    expect(row.auto).toBe(true);
    expect(row.incompatibleReason).toBe("пара не влезает");
    expect(row.total).toBeNull();
  });

  it("авто-пара без общих длин — итог null", () => {
    const pair = {
      techcardId: 7,
      productA: makeProduct({ id: 1, sku: "ЮП-A", perimeter_mm: 64.2, mount_width_mm: 19.35, lengths_mm: [2780] }),
      productB: makeProduct({ id: 2, sku: "ЮП-B", perimeter_mm: 64.2, mount_width_mm: 19.35, lengths_mm: [3500] }),
      perHanger: 36,
    };
    const [row] = buildPairedHangerCalcRows([pair], new Map(), new Map());
    expect(row.auto).toBe(true);
    expect(row.primaryLength).toBeNull();
    expect(row.total).toBeNull();
  });
});
