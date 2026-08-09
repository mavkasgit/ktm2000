/**
 * Pure-логика таблицы «Расчёт подвесов» (#64): построение batch-запроса
 * и строк-вьюмоделей. Без React и side effects — покрыто vitest.
 */
import type { Product } from "@/shared/api/products";
import type { HangerCalcItem, HangerCalcResult, HangerSettings, PairedHangerCalcItem } from "@/shared/api/hangerCalc";
import type { Techcard } from "@/shared/api/techcards";
import {
  entryForLength,
  isHangerAutoMode,
  lengthKey,
  primaryLength,
  productLengths,
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
export function buildCalcItems(
  products: Product[],
  settings: HangerSettings,
): BuildCalcItemsResult {
  const items: HangerCalcItem[] = [];
  const refs: CalcItemRef[] = [];
  const incompatible = new Map<number, string>();

  for (const product of products) {
    if (!isHangerAutoMode(product)) continue;
    const reason = incompatibilityReason(product.mount_width_mm, settings);
    if (reason) {
      incompatible.set(product.id, reason);
      continue;
    }
    for (const lengthMm of productLengths(product)) {
      items.push({
        perimeter_mm: product.perimeter_mm,
        mount_width_mm: product.mount_width_mm,
        length_mm: lengthMm,
      });
      refs.push({ productId: product.id, lengthMm });
    }
  }
  return { items, refs, incompatible };
}

/** Разложить результаты batch по productId → lengthKey (порядок = порядок items). */
export function resultsToCalcMap(
  refs: CalcItemRef[],
  results: HangerCalcResult[],
): CalcMap {
  const map: CalcMap = new Map();
  refs.forEach((ref, index) => {
    const result = results[index];
    if (!result) return;
    let byLength = map.get(ref.productId);
    if (!byLength) {
      byLength = new Map();
      map.set(ref.productId, byLength);
    }
    byLength.set(lengthKey(ref.lengthMm), result);
  });
  return map;
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
    const lengths = productLengths(product);
    const primaryLengthMm = primaryLength(product);
    const auto = isHangerAutoMode(product);
    const incompatibleReason = incompatible.get(product.id) ?? null;
    const byLength = calcMap.get(product.id);
    const primaryResult =
      auto && primaryLengthMm != null
        ? byLength?.get(lengthKey(primaryLengthMm)) ?? null
        : null;
    const primaryEntry = primaryLengthMm != null
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

// ─── Парные техкарты (#58/#67) ──────────────────────────────────────────────

/** Общие длины пары: пересечение списков длин артикулов A и B (#67). */
export function intersectLengths(a: number[], b: number[]): number[] {
  const setB = new Set(b);
  return a.filter((len) => setB.has(len));
}

/** techcardId → lengthKey → результат совместного расчёта. */
export type PairedCalcMap = Map<number, Map<string, HangerCalcResult>>;

/** Разрешённая пара: парная техкарта + её два артикула-компонента. */
export type PairedPair = {
  techcardId: number;
  productA: Product;
  productB: Product;
  /** Ручное N пары — инвариант равенства (#67): a == b, храним одно значение. */
  perHanger: number | null;
};

/**
 * Сопоставить парные техкарты с артикулами из загруженного набора. Пары, у
 * которых хотя бы один компонент отсутствует в наборе, пропускаются — парная
 * строка показывается только когда оба артикула видны рядом с одиночными.
 */
export function resolvePairs(techcards: Techcard[], products: Product[]): PairedPair[] {
  const byId = new Map(products.map((p) => [Number(p.id), p]));
  const pairs: PairedPair[] = [];
  for (const tc of techcards) {
    if (tc.processing_type !== "paired_processing") continue;
    const componentIds = (tc.techcard_lines ?? [])
      .map((line) => Number(line.component_product_id))
      .filter((id) => Number.isFinite(id));
    if (componentIds.length < 2) continue;
    const productA = byId.get(componentIds[0]);
    const productB = byId.get(componentIds[1]);
    if (!productA || !productB) continue;
    pairs.push({
      techcardId: Number(tc.id),
      productA,
      productB,
      perHanger: tc.quantity_a_per_item ?? tc.quantity_b_per_item ?? null,
    });
  }
  return pairs;
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

export type PairedCalcItemRef = { techcardId: number; lengthMm: number };

export type BuildPairedCalcItemsResult = {
  items: PairedHangerCalcItem[];
  refs: PairedCalcItemRef[];
  /** techcardId → причина несовместимости пары. */
  incompatible: Map<number, string>;
};

/**
 * Items для POST /hanger-calc/paired: каждая авто-пара × общая длина.
 * Авто только когда оба артикула авто; иначе пара не отправляется (ручная).
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
    if (!isHangerAutoMode(pair.productA) || !isHangerAutoMode(pair.productB)) continue;
    const reason = pairedIncompatibilityReason(
      pair.productA.mount_width_mm,
      pair.productB.mount_width_mm,
      settings,
    );
    if (reason) {
      incompatible.set(pair.techcardId, reason);
      continue;
    }
    for (const lengthMm of intersectLengths(productLengths(pair.productA), productLengths(pair.productB))) {
      items.push({
        perimeter_a_mm: pair.productA.perimeter_mm,
        mount_width_a_mm: pair.productA.mount_width_mm,
        perimeter_b_mm: pair.productB.perimeter_mm,
        mount_width_b_mm: pair.productB.mount_width_mm,
        length_mm: lengthMm,
      });
      refs.push({ techcardId: pair.techcardId, lengthMm });
    }
  }
  return { items, refs, incompatible };
}

/** Разложить результаты совместного batch по techcardId → lengthKey. */
export function resultsToPairedCalcMap(
  refs: PairedCalcItemRef[],
  results: HangerCalcResult[],
): PairedCalcMap {
  const map: PairedCalcMap = new Map();
  refs.forEach((ref, index) => {
    const result = results[index];
    if (!result) return;
    let byLength = map.get(ref.techcardId);
    if (!byLength) {
      byLength = new Map();
      map.set(ref.techcardId, byLength);
    }
    byLength.set(lengthKey(ref.lengthMm), result);
  });
  return map;
}

export type PairedHangerCalcRow = {
  kind: "paired";
  techcardId: number;
  productA: Product;
  productB: Product;
  label: string;
  perHanger: number | null;
  lengths: number[];
  primaryLength: number | null;
  auto: boolean;
  incompatibleReason: string | null;
  primaryResult: HangerCalcResult | null;
  total: number | null;
  limiter: "area" | "size" | null;
  areaM2: number | null;
};

/**
 * Вьюмодели парных строк: разбивка — по первой общей длине (по возрастанию).
 * Авто-пара — совместный расчёт; ручная (не оба авто) — только ручное N.
 */
export function buildPairedHangerCalcRows(
  pairs: PairedPair[],
  calcMap: PairedCalcMap,
  incompatible: Map<number, string>,
): PairedHangerCalcRow[] {
  return pairs.map((pair) => {
    const lengths = intersectLengths(productLengths(pair.productA), productLengths(pair.productB));
    const primaryLengthMm = lengths[0] ?? null;
    const auto = isHangerAutoMode(pair.productA) && isHangerAutoMode(pair.productB);
    const incompatibleReason = incompatible.get(pair.techcardId) ?? null;
    const primaryResult =
      auto && primaryLengthMm != null
        ? calcMap.get(pair.techcardId)?.get(lengthKey(primaryLengthMm)) ?? null
        : null;

    let total: number | null = null;
    if (auto && primaryResult?.is_calculable) {
      total = primaryResult.total;
    } else if (!auto) {
      total = pair.perHanger;
    }

    return {
      kind: "paired",
      techcardId: pair.techcardId,
      productA: pair.productA,
      productB: pair.productB,
      label: `${pair.productA.sku} + ${pair.productB.sku}`,
      perHanger: pair.perHanger,
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
