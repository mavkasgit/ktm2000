/**
 * Pure-логика таблицы «Расчёт подвесов» (#64): построение batch-запроса
 * и строк-вьюмоделей. Без React и side effects — покрыто vitest.
 */
import type { Product, ProductPairCatalogEntry } from "@/shared/api/products";
import type { HangerCalcItem, HangerCalcResult, HangerSettings, PairedHangerCalcItem } from "@/shared/api/hangerCalc";
import type { SortConfig } from "@/shared/hooks/useTableQueryEngine";
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
import { fmtQtyPrecise } from "@/shared/lib/quantityFormat";

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


/** Значения строки, по которым работает общий поиск таблицы подвесов. */
export function rowSearchValues(row: HangerCalcRow | PairedHangerCalcRow): string[] {
  const products = row.kind === "paired" ? [row.productA, row.productB] : [row.product];
  const values = [rowSku(row)];
  for (const product of products) {
    for (const length of product.lengths ?? []) {
      values.push(String(length.length_mm), String(effectiveRawLength(length)));
    }
  }
  return values;
}


/** Причина «—» в колонке N: ручной режим, для этой длины нормы нет. */
const manualNoNormReason = (lengthMm: number): string =>
  `Ручной режим: для длины ${fmtQtyPrecise(lengthMm)} мм не задана норма`;

/** Причина «—» в разбивке: ручной режим, расчёт по периметру не запускался. */
const MANUAL_NO_CALC_REASON = "Ручной режим: расчёт по периметру не запускался";

/** Причина «—» в авто-режиме: результата по длине нет. */
const NO_CALC_DATA_REASON = "Расчёт невозможен: не хватает данных";

/**
 * Подстрока строки расчёта: одна на длину (ADR-0050). Строка принадлежит
 * артикулу (или паре), подстроки — его длинам: N подстроки — N длины, а не
 * N артикула. Разбивка каждой подстроки своя, потому что формула подвеса
 * считается по сырьевой длине этой строки реестра.
 */
export type HangerLengthLine = {
  /** Нормальная длина из реестра; null — у артикула длин нет вовсе. */
  lengthMm: number | null;
  /** Подпись длины: «2700» либо «2700 / сырьё 2750». */
  lengthLabel: string;
  isPrimary: boolean;
  /** Результат расчёта этой длины; в ручном режиме — null. */
  result: HangerCalcResult | null;
  /** N этой длины: авто-итог или ручная норма; null — значения нет. */
  total: number | null;
  /** Источник N по режиму подвеса. */
  source: "auto" | "manual" | null;
  /** Почему N напечатан «—». */
  totalReason: string | null;
  /** Почему разбивка напечатана «—». */
  breakdownReason: string | null;
};

/** Подпись нормальной и сырьевой длины: сырьё печатается, только если отличается. */
export function formatLengthLabel(normalMm: number, rawMm: number): string {
  return rawMm === normalMm ? `${normalMm}` : `${normalMm} / сырьё ${rawMm}`;
}

/** То же для пары: сырьё обеих сторон печатается, только если отличается. */
export function formatPairedLengthLabel(
  normalMm: number,
  rawAMm: number,
  rawBMm: number,
): string {
  if (rawAMm === normalMm && rawBMm === normalMm) return `${normalMm}`;
  const raw = rawAMm === rawBMm ? `сырьё ${rawAMm}` : `сырьё ${rawAMm} и ${rawBMm}`;
  return `${normalMm} / ${raw}`;
}

export type BuildLengthLinesInput = {
  lengths: number[];
  /** Подпись длины строки: у одиночной «2700» / «2700 / сырьё 2750». */
  labelOf: (lengthMm: number) => string;
  primaryLengthMm: number | null;
  auto: boolean;
  /** Несовместимость — свойство артикула, а не длины: причина у всех подстрок. */
  incompatibleReason: string | null;
  /** Результат расчёта длины (авто-режим). */
  resultOf: (lengthMm: number) => HangerCalcResult | null;
  /** Ручная N длины. */
  manualOf: (lengthMm: number) => number | null;
  /** Причина для артикула без длин. */
  noLengthsReason: string;
};

/**
 * Подстроки строки: по одной на длину, по возрастанию. Режим выбирает,
 * откуда берётся N (ADR-0047, #127): авто — результат движка по этой длине,
 * ручной — норма из словаря под ключом этой длины, без фолбэка.
 */
export function buildLengthLines(input: BuildLengthLinesInput): HangerLengthLine[] {
  const { lengths, labelOf, primaryLengthMm, auto, incompatibleReason, resultOf, manualOf, noLengthsReason } = input;
  if (lengths.length === 0) {
    return [{
      lengthMm: null,
      lengthLabel: "—",
      isPrimary: false,
      result: null,
      total: null,
      source: null,
      totalReason: noLengthsReason,
      breakdownReason: noLengthsReason,
    }];
  }
  return lengths.map((lengthMm) => {
    const base = {
      lengthMm,
      lengthLabel: labelOf(lengthMm),
      isPrimary: primaryLengthMm != null && lengthMm === primaryLengthMm,
    };
    if (incompatibleReason != null) {
      return {
        ...base,
        result: null,
        total: null,
        source: null,
        totalReason: incompatibleReason,
        breakdownReason: incompatibleReason,
      };
    }
    if (!auto) {
      const manual = manualOf(lengthMm);
      const reason = manual == null ? manualNoNormReason(lengthMm) : null;
      return {
        ...base,
        result: null,
        total: manual,
        source: "manual",
        totalReason: reason,
        breakdownReason: reason ?? MANUAL_NO_CALC_REASON,
      };
    }
    const result = resultOf(lengthMm);
    if (!result?.is_calculable) {
      return {
        ...base,
        result: result ?? null,
        total: null,
        source: "auto",
        totalReason: result?.reason ?? NO_CALC_DATA_REASON,
        breakdownReason: result?.reason ?? NO_CALC_DATA_REASON,
      };
    }
    return {
      ...base,
      result,
      total: result.total,
      source: "auto",
      totalReason: null,
      breakdownReason: null,
    };
  });
}

export type HangerCalcRow = {
  kind: "single";
  product: Product;
  lengths: number[];
  primaryLength: number | null;
  auto: boolean;
  incompatibleReason: string | null;
  /** Подстроки по длинам — то, что печатается в колонках (ADR-0050). */
  lines: HangerLengthLine[];
  /**
   * Итог и лимитер **основной** длины: по ним сортируется, фильтруется и
   * собирается попапер колонки. Внутри строки итогов столько же, сколько
   * подстрок, поэтому единственное число для этих операций — агрегат
   * основной длины, а не «первый» или «минимальный» по строкам.
   */
  total: number | null;
  limiter: "area" | "size" | null;
};

/**
 * Вьюмодели строк таблицы: одна строка на артикул, внутри — подстроки по
 * длинам реестра (ADR-0050). Основная длина — выбор пользователя (#81,
 * ADR-0013), её помечают; разбивка печатается по каждой длине.
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
    const records = product.lengths ?? [];
    const lines = buildLengthLines({
      lengths,
      labelOf: (lengthMm) => {
        const record = records.find((length) => length.length_mm === lengthMm);
        return formatLengthLabel(lengthMm, record ? effectiveRawLength(record) : lengthMm);
      },
      primaryLengthMm,
      auto,
      incompatibleReason,
      resultOf: (lengthMm) => byLength?.get(lengthKey(lengthMm)) ?? null,
      // У листа длина одна по определению, поэтому там допустим фолбэк на
      // единственную запись словаря (ADR-0047 п. 4): он восстанавливает
      // значение при смене длины полотна, а не угадывает.
      manualOf: (lengthMm) =>
        (sheet
          ? sheetHangerEntry(product.quantity_per_hanger)?.manual
          : entryForLength(product.quantity_per_hanger, lengthMm)?.manual) ?? null,
      noLengthsReason: auto
        ? "Расчёт невозможен: у артикула нет длин"
        : "Ручной режим: у артикула нет длин",
    });
    const primaryLine = lines.find((line) => line.isPrimary) ?? null;

    return {
      kind: "single",
      product,
      lengths,
      primaryLength: primaryLengthMm,
      auto,
      incompatibleReason,
      lines,
      total: primaryLine?.total ?? null,
      limiter: primaryLine?.result?.limiter ?? null,
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
  /** Ручная N пары по длине (lengthKey → N); режим авто — не используется. */
  manualPerLength: Record<string, number | null>;
  /** Суммы периметра/габарита пары (идут в формулы совместного расчёта). */
  perimeterSum: number | null;
  widthSum: number | null;
  /** Подстроки по длинам пары — те же подстроки, что у одиночной строки. */
  lines: HangerLengthLine[];
  /** Итог и лимитер основной длины пары — ключ сортировки и попапера. */
  total: number | null;
  limiter: "area" | "size" | null;
};

/**
 * Вьюмодели парных строк: одна строка на пару, внутри — подстроки по длинам
 * пары (ADR-0050). Режим пары выведенный (#150): авто (совместный расчёт) —
 * только если оба артикула в режиме auto; иначе ручное N из словаря пары на
 * каждую длину.
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
    const perimeterSum =
      pair.productA.perimeter_mm != null && pair.productB.perimeter_mm != null
        ? Number((pair.productA.perimeter_mm + pair.productB.perimeter_mm).toFixed(2))
        : null;
    const widthSum =
      pair.productA.mount_width_mm != null && pair.productB.mount_width_mm != null
        ? Number((pair.productA.mount_width_mm + pair.productB.mount_width_mm).toFixed(2))
        : null;

    const byLength = calcMap.get(pair.pairId);
    const recordsA = pair.productA.lengths ?? [];
    const recordsB = pair.productB.lengths ?? [];
    const lines = buildLengthLines({
      lengths,
      labelOf: (lengthMm) => {
        const rawA = recordsA.find((length) => length.length_mm === lengthMm);
        const rawB = recordsB.find((length) => length.length_mm === lengthMm);
        return formatPairedLengthLabel(
          lengthMm,
          rawA ? effectiveRawLength(rawA) : lengthMm,
          rawB ? effectiveRawLength(rawB) : lengthMm,
        );
      },
      primaryLengthMm,
      auto,
      incompatibleReason,
      resultOf: (lengthMm) => byLength?.get(lengthKey(lengthMm)) ?? null,
      manualOf: (lengthMm) => pair.manualPerLength[lengthKey(lengthMm)] ?? null,
      noLengthsReason: auto
        ? "Расчёт невозможен: у пары нет общих длин"
        : "Ручной режим: у пары нет общих длин",
    });
    const primaryLine = lines.find((line) => line.isPrimary) ?? null;


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
      manualPerLength: pair.manualPerLength,
      perimeterSum,
      widthSum,
      lines,
      total: primaryLine?.total ?? null,
      limiter: primaryLine?.result?.limiter ?? null,
    };
  });
}

// ─── Порядок строк таблицы подвесов ────────────────────────────────────────

/** Сортируемые колонки таблицы подвесов (заголовки `HangerCalcTable`). */
export type HangerCalcSortField = "sku" | "total" | "limiter";

function sortValue(
  row: HangerCalcRow | PairedHangerCalcRow,
  field: HangerCalcSortField,
): string | number | null {
  if (field === "sku") return rowSku(row);
  if (field === "total") return row.total;
  return row.limiter ? LIMITER_LABELS[row.limiter] : null;
}

/**
 * Порядок объединённой таблицы (одиночные + парные строки) по мультисортировке.
 *
 * Сортируется весь массив строк, включая парные: `sku` уходит на сервер
 * (`sort=sku:<order>`), но сервер сортирует только одиночные строки — парные
 * приходят отдельным запросом и в общий порядок не попадали. Клиент применяет
 * всю цепочку приоритетов, поэтому серверный ключ `sku` остаётся старшим
 * независимо от добавленных колонок, а при `sku` не на первом месте
 * сортировка по нему выполняется на клиенте целиком.
 *
 * Строки без значения (`total`/`limiter` = null) уходят в конец при любом
 * направлении — как `NULLS LAST` в серверной сортировке позиций плана.
 */
export function sortHangerCalcRows<T extends HangerCalcRow | PairedHangerCalcRow>(
  rows: readonly T[],
  sortConfigs: readonly SortConfig<HangerCalcSortField>[],
): T[] {
  if (sortConfigs.length === 0) return [...rows];
  return [...rows].sort((a, b) => {
    for (const cfg of sortConfigs) {
      const aValue = sortValue(a, cfg.field);
      const bValue = sortValue(b, cfg.field);
      if (aValue == null && bValue == null) continue;
      if (aValue == null) return 1;
      if (bValue == null) return -1;
      const cmp =
        typeof aValue === "number" && typeof bValue === "number"
          ? aValue - bValue
          : String(aValue).localeCompare(String(bValue), "ru");
      if (cmp !== 0) return cfg.order === "asc" ? cmp : -cmp;
    }
    return 0;
  });
}
