/**
 * Хелперы per-length словаря «кол-во на подвес» (#60, #64, #65).
 * Чистые функции без side effects, ключи — длины в мм.
 * Режим auto/manual (#126, #127): отображается и используется значение
 * выбранного режима — никакого data-driven приоритета «авто > ручное».
 */
import type { DimensionState, HangerMode, HangerQuantityValue, QuantityPerHangerDict } from "@/shared/api/products";

export type HangerValueSource = "auto" | "manual";

export type EffectiveHangerValue = {
  value: number | null;
  source: HangerValueSource | null;
};

/** Ключ длины в словаре: зеркалит backend `_length_key` (целые без ".0"). */
export function lengthKey(lengthMm: number): string {
  return String(lengthMm);
}

/** Авто-режим data-driven: оба поля (периметр И габарит) заполнены и > 0 (#59). */
export function isHangerAutoMode(fields: {
  perimeter_mm?: number | null;
  mount_width_mm?: number | null;
}): boolean {
  const { perimeter_mm: perimeter, mount_width_mm: mountWidth } = fields;
  return (
    typeof perimeter === "number" && Number.isFinite(perimeter) && perimeter > 0 &&
    typeof mountWidth === "number" && Number.isFinite(mountWidth) && mountWidth > 0
  );
}

/** Артикул-лист (2D/3D) (#126): подвес считается по площади полотна. */
export function isSheetState(state: DimensionState | null | undefined): boolean {
  return state === "area" || state === "volume";
}

export type SheetDims = {
  lengthMm: number | null;
  widthMm: number | null;
  heightMm: number | null;
};

/** Оси полотна листа из типового набора product_dimensions (ProductOut.dimensions). */
export function sheetDims(product: {
  dimensions?: Record<string, number> | null;
}): SheetDims {
  const dims = product.dimensions ?? {};
  return {
    lengthMm: dims.length_mm ?? null,
    widthMm: dims.width_mm ?? null,
    heightMm: dims.height_mm ?? null,
  };
}

/** Длины полотна листа (ноль или одна запись) — зеркалит ключ словаря бэкенда. */
export function sheetLengths(product: {
  dimensions?: Record<string, number> | null;
}): number[] {
  const { lengthMm } = sheetDims(product);
  return lengthMm != null ? [lengthMm] : [];
}

/**
 * Эффективное значение записи по явному режиму (#126): режим выбирает,
 * какое из двух хранимых значений показывать; после ручной смены флага
 * приоритет у ручного.
 */
export function effectiveForMode(
  entry: HangerQuantityValue | null | undefined,
  mode: HangerMode | null | undefined,
): EffectiveHangerValue {
  const resolved: HangerMode = mode === "manual" ? "manual" : "auto";
  const value = resolved === "manual" ? entry?.manual ?? null : entry?.auto ?? null;
  return { value, source: resolved };
}

/**
 * Нормализовать массив длин: фильтр мусора, дедуп, сортировка по возрастанию.
 * Базовая функция для всех вариантов (мерж lengths_mm + legacy, raw array).
 */
export function normalizeLengths(values: Array<number | null | undefined>): number[] {
  return [...new Set(values.filter((v): v is number => typeof v === "number" && Number.isFinite(v) && v > 0))]
    .sort((a, b) => a - b);
}

/** Длины артикула по возрастанию (lengths_mm + legacy length_mm); первая — основная по умолчанию. */
export function productLengths(product: {
  lengths_mm?: number[] | null;
  length_mm?: number | null;
}): number[] {
  return normalizeLengths([...(product.lengths_mm ?? []), product.length_mm ?? undefined]);
}

/** Основная длина артикула (#81): явный выбор или первая по возрастанию. */
export function primaryLength(product: {
  primary_length_mm?: number | null;
  lengths_mm?: number[] | null;
  length_mm?: number | null;
}): number | null {
  if (
    typeof product.primary_length_mm === "number" &&
    Number.isFinite(product.primary_length_mm) &&
    product.primary_length_mm > 0
  ) {
    return product.primary_length_mm;
  }
  const lengths = productLengths(product);
  return lengths[0] ?? null;
}

export function entryForLength(
  dict: QuantityPerHangerDict | null | undefined,
  lengthMm: number,
): HangerQuantityValue | null {
  if (!dict) return null;
  const entry = dict[lengthKey(lengthMm)];
  return entry ?? null;
}

/**
 * Эффективное значение записи для длины: строго по режиму (#127).
 * Режим выбирает, какое из двух хранимых значений брать — без fallback.
 */
export function effectiveForLength(
  dict: QuantityPerHangerDict | null | undefined,
  lengthMm: number,
  mode: HangerMode | null | undefined,
): EffectiveHangerValue {
  return effectiveForMode(entryForLength(dict, lengthMm), mode);
}

/**
 * Единственная запись словаря листа (#126): у листов ровно одна запись
 * под ключом длины полотна. Пусто/нет словаря — null.
 */
export function sheetHangerEntry(
  dict: QuantityPerHangerDict | null | undefined,
): HangerQuantityValue | null {
  if (!dict) return null;
  const keys = Object.keys(dict);
  if (keys.length === 0) return null;
  return dict[keys[0]] ?? null;
}

export type PrimaryHangerValue = EffectiveHangerValue & { lengthMm: number };

/**
 * Значение для основной длины (#81): явный выбор или первая по возрастанию.
 * Источник — по режиму подвеса (#127). null — нет длин или нет значения.
 */
export function primaryHangerValue(product: {
  primary_length_mm?: number | null;
  lengths_mm?: number[] | null;
  length_mm?: number | null;
  quantity_per_hanger?: QuantityPerHangerDict | null;
  hanger_mode?: HangerMode | null;
}): PrimaryHangerValue | null {
  const lengthMm = primaryLength(product);
  if (lengthMm == null) return null;
  const effective = effectiveForLength(product.quantity_per_hanger ?? null, lengthMm, product.hanger_mode);
  if (effective.value == null) return null;
  return { lengthMm, ...effective };
}

/** Плоская карта manual-значений {lengthKey: int} — для сравнения в формах. */
export function manualByLength(
  dict: QuantityPerHangerDict | null | undefined,
): Record<string, number> {
  const result: Record<string, number> = {};
  if (!dict) return result;
  for (const [key, entry] of Object.entries(dict)) {
    if (entry?.manual != null) result[key] = entry.manual;
  }
  return result;
}
