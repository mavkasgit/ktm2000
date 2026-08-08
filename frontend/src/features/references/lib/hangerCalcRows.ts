/**
 * Pure-логика таблицы «Расчёт подвесов» (#64): построение batch-запроса
 * и строк-вьюмоделей. Без React и side effects — покрыто vitest.
 */
import type { Product } from "@/shared/api/products";
import type { HangerCalcItem, HangerCalcResult, HangerSettings } from "@/shared/api/hangerCalc";
import {
  effectiveValue,
  entryForLength,
  isHangerAutoMode,
  lengthKey,
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
  product: Product;
  lengths: number[];
  primaryLength: number | null;
  auto: boolean;
  incompatibleReason: string | null;
  primaryResult: HangerCalcResult | null;
  primaryManual: number | null;
  /** Итог основной длины: авто-итог, иначе ручное значение. */
  total: number | null;
  limiter: "area" | "size" | null;
  areaM2: number | null;
};

/**
 * Вьюмодели строк таблицы: разбивка — по основной длине (первая из
 * ProductLength по возрастанию), ручной артикул — без разбивки (#64, п. 14).
 */
export function buildHangerCalcRows(
  products: Product[],
  calcMap: CalcMap,
  incompatible: Map<number, string>,
): HangerCalcRow[] {
  return products.map((product) => {
    const lengths = productLengths(product);
    const primaryLength = lengths[0] ?? null;
    const auto = isHangerAutoMode(product);
    const incompatibleReason = incompatible.get(product.id) ?? null;
    const byLength = calcMap.get(product.id);
    const primaryResult =
      auto && primaryLength != null
        ? byLength?.get(lengthKey(primaryLength)) ?? null
        : null;
    const primaryEntry = primaryLength != null
      ? entryForLength(product.quantity_per_hanger, primaryLength)
      : null;
    const primaryManual = primaryEntry?.manual ?? null;

    let total: number | null = null;
    if (auto && primaryResult?.is_calculable) {
      total = primaryResult.total;
    } else if (!auto) {
      total = effectiveValue(primaryEntry).value;
    }

    return {
      product,
      lengths,
      primaryLength,
      auto,
      incompatibleReason,
      primaryResult,
      primaryManual,
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
