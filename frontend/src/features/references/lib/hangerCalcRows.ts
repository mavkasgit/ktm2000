/**
 * Pure-логика таблицы «Расчёт подвесов» (#64): построение batch-запроса
 * и строк-вьюмоделей. Без React и side effects — покрыто vitest.
 */
import type { Product, ProductPairCatalogEntry } from "@/shared/api/products";
import type { HangerCalcItem, HangerCalcResult, HangerSettings, PairedHangerCalcItem } from "@/shared/api/hangerCalc";
import {
  effectiveRawLength,
  entryForLength,
  isHangerAutoMode,
  isSheetState,
  lengthKey,
  primaryLength,
  productLengths,
  sheetDims,
  sheetHangerEntry,
  sheetLengths,
} from "@/shared/lib/hangerQuantity";

/** productId → lengthKey → результат расчёта. */
export type CalcMap = Map<number, Map<string, HangerCalcResult>>;

export type CalcItemRef = { productId: number; lengthMm: number };

export type BuildCalcItemsResult = {
  items: HangerCalcItem[];
  refs: CalcItemRef[];
  /** productId → причина несовместимости (габарит + зазор > длина клюшки). */
  incompatible: Map<number, string>;
};

/** Причина несовместимости габарита с константами подвеса, либо null. */
export function incompatibilityReason(
  mountWidthMm: number | null,
  settings: HangerSettings,
): string | null {
  if (mountWidthMm == null) return null;
  if (mountWidthMm + settings.gap_mm > settings.rod_length_mm) {
    return `Габарит ${mountWidthMm} мм + зазор ${settings.gap_mm} мм превышает рабочую длину клюшки ${settings.rod_length_mm} мм`;
  }
  return null;
}

/**
 * Items для batch POST /hanger-calc: каждое авто-изделие × каждая длина.
 * Ручные (без периметра/габарита) и несовместимые не отправляются —
 * несовместимость помечается локально, чтобы один плохой артикул не
 * рвал весь batch (эндпоинт вернул бы 422 на весь запрос).
 */
export function buildCalcItems(products: Product[], settings: HangerSettings): BuildCalcItemsResult {
  const items: HangerCalcItem[] = [];
  const refs: CalcItemRef[] = [];
  const incompatible = new Map<number, string>();
  for (const product of products) {
    if (isSheetState(product.dimension_state)) {
      if ((product.hanger_mode ?? "auto") !== "auto") continue;
      const { lengthMm, widthMm, heightMm } = sheetDims(product);
      if (lengthMm == null) continue;
      items.push({ kind: "sheet", perimeter_mm: null, mount_width_mm: null, length_mm: lengthMm, width_mm: widthMm, height_mm: product.dimension_state === "volume" ? heightMm : null });
      refs.push({ productId: product.id, lengthMm });
      continue;
    }
    if ((product.hanger_mode ?? "auto") !== "auto" || !isHangerAutoMode(product)) continue;
    const reason = incompatibilityReason(product.mount_width_mm, settings);
    if (reason) { incompatible.set(product.id, reason); continue; }
    for (const length of product.lengths ?? []) {
      const lengthMm = length.length_mm;
      items.push({ perimeter_mm: product.perimeter_mm, mount_width_mm: product.mount_width_mm, length_mm: effectiveRawLength(length) });
      refs.push({ productId: product.id, lengthMm });
    }
  }
  return { items, refs, incompatible };
}

/** Разложить результаты batch по {id} → lengthKey (порядок = порядок items). */
function resultsToLengthMap(
  refs: Array<{ id: number; lengthMm: number }>,
  results: HangerCalcResult[],
): Map<number, Map<string, HangerCalcResult>> {
  const map = new Map<number, Map<string, HangerCalcResult>>();
  refs.forEach((ref, index) => {
    const result = results[index];
    if (!result) return;
    let byLength = map.get(ref.id);
    if (!byLength) {
      byLength = new Map();
      map.set(ref.id, byLength);
    }
    byLength.set(lengthKey(ref.lengthMm), result);
  });
  return map;
}

/** Разложить результаты batch по productId → lengthKey (порядок = порядок items). */
export function resultsToCalcMap(refs: CalcItemRef[], results: HangerCalcResult[]): CalcMap {
  return resultsToLengthMap(
    refs.map((ref) => ({ id: ref.productId, lengthMm: ref.lengthMm })),
    results,
  );
}

/** SKU строки таблицы: одиночный артикул или метка «A + B» парной строки. */
export function rowSku(row: HangerCalcRow | PairedHangerCalcRow): string {
  return row.kind === "paired" ? row.label : row.product.sku;
}

export type HangerCalcRow = {
  kind: "single";
  product: Product;
  lengths: number[];
  primaryLength: number | null;
  auto: boolean;
  incompatibleReason: string | null;
  primaryResult: HangerCalcResult | null;
  /** Итог основной длины: авто-итог, иначе ручное значение (без авто-приоритета). */
  total: number | null;
  limiter: "area" | "size" | null;
  areaM2: number | null;
};

/**
 * Вьюмодели строк таблицы: разбивка — по основной длине (#81: выбранная
 * is_primary, иначе первая из ProductLength по возрастанию), ручной
 * артикул — без разбивки (#64, п. 14).
 */
export function buildHangerCalcRows(
  products: Product[],
  calcMap: CalcMap,
  incompatible: Map<number, string>,
): HangerCalcRow[] {
  return products.map((product) => {
    const sheet = isSheetState(product.dimension_state);
    // Режим строки — явный hanger_mode (#126 листы, #127 профили): значение
    // следует выбранному режиму, а не наличию периметра/габарита.
    const auto = (product.hanger_mode ?? "auto") === "auto";
    const lengths = sheet ? sheetLengths(product) : productLengths(product);
    const primaryLengthMm = sheet
      ? sheetDims(product).lengthMm ?? lengths[0] ?? null
      : primaryLength(product);
    const incompatibleReason = incompatible.get(product.id) ?? null;
    const byLength = calcMap.get(product.id);
    const primaryResult =
      auto && primaryLengthMm != null
        ? byLength?.get(lengthKey(primaryLengthMm)) ?? null
        : null;
    const primaryEntry = sheet
      ? sheetHangerEntry(product.quantity_per_hanger)
      : primaryLengthMm != null
        ? entryForLength(product.quantity_per_hanger, primaryLengthMm)
        : null;

    let total: number | null = null;
    if (auto && primaryResult?.is_calculable) {
      total = primaryResult.total;
    } else if (!auto) {
      // Ручной режим: итог — только manual (без приоритета auto>manual,
      // потому что устаревший auto в ручной строке не должен давать итог).
      total = primaryEntry?.manual ?? null;
    }

    return {
      kind: "single",
      product,
      lengths,
      primaryLength: primaryLengthMm,
      auto,
      incompatibleReason,
      primaryResult,
      total,
      limiter: primaryResult?.limiter ?? null,
      areaM2: primaryResult?.area_m2 ?? null,
    };
  });
}

export const LIMITER_LABELS: Record<"area" | "size", string> = {
  area: "площадь",
  size: "размер",
};

// ─── Пары сырьевых артикулов (pairs-API, #150) ───────────────────────────────

/** pairId → lengthKey → результат совместного расчёта. */
export type PairedCalcMap = Map<number, Map<string, HangerCalcResult>>;

/** Разрешённая пара из pairs-API + её два артикула. */
export type PairedPair = {
  pairId: number;
  productA: Product;
  productB: Product;
  /** Длины пары — пересечение длин A и B (считает сервер, по возрастанию). */
  lengths: number[];
  /** Ручная N пары по длине (lengthKey → N), из словаря пары. */
  manualPerLength: Record<string, number | null>;
};

/** Режим пары выведенный (#150): авто — только если оба артикула в режиме auto. */
export function pairModeAuto(a: Product, b: Product): boolean {
  return (a.hanger_mode ?? "auto") === "auto" && (b.hanger_mode ?? "auto") === "auto";
}

/**
 * Сопоставить пары из pairs-API с артикулами из загруженного набора. Пропускаются:
 * пары, у которых хотя бы один артикул не в наборе (строка показывается, только
 * когда оба артикула видны рядом с одиночными), и пары с пустым пересечением
 * длин — на длине, где существует N, нет (#150: lengths: [] не роняет список).
 */
export function resolvePairs(pairs: ProductPairCatalogEntry[], products: Product[]): PairedPair[] {
  const byId = new Map(products.map((p) => [Number(p.id), p]));
  const resolved: PairedPair[] = [];
  for (const pair of pairs) {
    if (pair.lengths.length === 0) continue;
    const productA = byId.get(Number(pair.product_a_id));
    const productB = byId.get(Number(pair.product_b_id));
    if (!productA || !productB) continue;
    const manualPerLength: Record<string, number | null> = {};
    for (const [key, value] of Object.entries(pair.quantity_per_hanger ?? {})) {
      manualPerLength[key] = value?.manual ?? null;
    }
    resolved.push({
      pairId: Number(pair.id),
      productA,
      productB,
      lengths: pair.lengths,
      manualPerLength,
    });
  }
  return resolved;
}

/** Причина несовместимости пары с константами подвеса, либо null (#67). */
export function pairedIncompatibilityReason(
  widthA: number | null,
  widthB: number | null,
  settings: HangerSettings,
): string | null {
  if (widthA == null || widthB == null) return null;
  const combined = widthA + widthB + settings.gap_mm * 2;
  const available = settings.rod_length_mm * settings.rod_count;
  if (combined > available) {
    return `Сумма габаритов пары ${widthA}+${widthB} + зазоры ${settings.gap_mm * 2} мм превышает рабочую длину клюшек ${available} мм`;
  }
  return null;
}

export type PairedCalcItemRef = { pairId: number; lengthMm: number };

export type BuildPairedCalcItemsResult = {
  items: PairedHangerCalcItem[];
  refs: PairedCalcItemRef[];
  /** pairId → причина несовместимости пары. */
  incompatible: Map<number, string>;
};

/**
 * Items для POST /hanger-calc/paired: каждая авто-пара × длина пары.
 * Авто только когда оба артикула в режиме auto И у движка есть данные
 * (периметр/габарит); иначе пара ручная — N берётся из словаря пары.
 * Несовместимые помечаются локально, чтобы один плохой не рвал весь batch.
 */
export function buildPairedCalcItems(
  pairs: PairedPair[],
  settings: HangerSettings,
): BuildPairedCalcItemsResult {
  const items: PairedHangerCalcItem[] = [];
  const refs: PairedCalcItemRef[] = [];
  const incompatible = new Map<number, string>();

  for (const pair of pairs) {
    // Режим пары — hanger_mode обоих артикулов; движку, кроме того, нужны
    // данные (периметр/габарит) — без них пара ведёт себя как ручная.
    if (!pairModeAuto(pair.productA, pair.productB)) continue;
    if (!isHangerAutoMode(pair.productA) || !isHangerAutoMode(pair.productB)) continue;
    const reason = pairedIncompatibilityReason(
      pair.productA.mount_width_mm,
      pair.productB.mount_width_mm,
      settings,
    );
    if (reason) {
      incompatible.set(pair.pairId, reason);
      continue;
    }
    for (const lengthMm of pair.lengths) {
      const recordA = (pair.productA.lengths ?? []).find((length) => length.length_mm === lengthMm);
      const recordB = (pair.productB.lengths ?? []).find((length) => length.length_mm === lengthMm);
      if (!recordA || !recordB || effectiveRawLength(recordA) !== effectiveRawLength(recordB)) continue;
      items.push({
        perimeter_a_mm: pair.productA.perimeter_mm,
        mount_width_a_mm: pair.productA.mount_width_mm,
        perimeter_b_mm: pair.productB.perimeter_mm,
        mount_width_b_mm: pair.productB.mount_width_mm,
        length_mm: effectiveRawLength(recordA),
      });
      refs.push({ pairId: pair.pairId, lengthMm });
    }
  }
  return { items, refs, incompatible };
}

/** Разложить результаты совместного batch по pairId → lengthKey. */
export function resultsToPairedCalcMap(
  refs: PairedCalcItemRef[],
  results: HangerCalcResult[],
): PairedCalcMap {
  return resultsToLengthMap(
    refs.map((ref) => ({ id: ref.pairId, lengthMm: ref.lengthMm })),
    results,
  );
}

export type PairedHangerCalcRow = {
  kind: "paired";
  pairId: number;
  productA: Product;
  productB: Product;
  label: string;
  lengths: number[];
  primaryLength: number | null;
  auto: boolean;
  incompatibleReason: string | null;
  primaryResult: HangerCalcResult | null;
  /** Ручная N пары по длине (lengthKey → N); режим авто — не используется. */
  manualPerLength: Record<string, number | null>;
  /** Суммы периметра/габарита пары (идут в формулы совместного расчёта). */
  perimeterSum: number | null;
  widthSum: number | null;
  total: number | null;
  limiter: "area" | "size" | null;
  areaM2: number | null;
};

/**
 * Вьюмодели парных строк: разбивка — по первой длине пары (по возрастанию).
 * Режим пары выведенный (#150): авто (совместный расчёт) — только если оба
 * артикула в режиме auto; иначе ручное N из словаря пары на каждую длину.
 */
export function buildPairedHangerCalcRows(
  pairs: PairedPair[],
  calcMap: PairedCalcMap,
  incompatible: Map<number, string>,
): PairedHangerCalcRow[] {
  return pairs.map((pair) => {
    const lengths = pair.lengths;
    const primaryLengthMm = lengths[0] ?? null;
    const auto = pairModeAuto(pair.productA, pair.productB);
    const incompatibleReason = incompatible.get(pair.pairId) ?? null;
    const primaryResult =
      auto && primaryLengthMm != null
        ? calcMap.get(pair.pairId)?.get(lengthKey(primaryLengthMm)) ?? null
        : null;

    const perimeterSum =
      pair.productA.perimeter_mm != null && pair.productB.perimeter_mm != null
        ? Number((pair.productA.perimeter_mm + pair.productB.perimeter_mm).toFixed(2))
        : null;
    const widthSum =
      pair.productA.mount_width_mm != null && pair.productB.mount_width_mm != null
        ? Number((pair.productA.mount_width_mm + pair.productB.mount_width_mm).toFixed(2))
        : null;

    let total: number | null = null;
    if (auto && primaryResult?.is_calculable) {
      total = primaryResult.total;
    } else if (!auto) {
      // Ручной режим: итог — ручное N основной длины (без авто-приоритета).
      total =
        (primaryLengthMm != null ? pair.manualPerLength[lengthKey(primaryLengthMm)] : null) ?? null;
    }

    return {
      kind: "paired",
      pairId: pair.pairId,
      productA: pair.productA,
      productB: pair.productB,
      label: `${pair.productA.sku} + ${pair.productB.sku}`,
      lengths,
      primaryLength: primaryLengthMm,
      auto,
      incompatibleReason,
      primaryResult,
      manualPerLength: pair.manualPerLength,
      perimeterSum,
      widthSum,
      total,
      limiter: primaryResult?.limiter ?? null,
      areaM2: primaryResult?.area_m2 ?? null,
    };
  });
}
