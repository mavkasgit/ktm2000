/**
 * Хелперы per-length словаря «кол-во на подвес» (#60, #64, #65).
 * Чистые функции без side effects: приоритет авто > ручное, ключи — длины в мм.
 */
import type { HangerQuantityValue, QuantityPerHangerDict } from "@/shared/api/products";

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

/**
 * Нормализовать массив длин: фильтр мусора, дедуп, сортировка по возрастанию.
 * Базовая функция для всех вариантов (мерж lengths_mm + legacy, raw array).
 */
export function normalizeLengths(values: Array<number | null | undefined>): number[] {
  return [...new Set(values.filter((v): v is number => typeof v === "number" && Number.isFinite(v) && v > 0))]
    .sort((a, b) => a - b);
}

/** Длины артикула по возрастанию (lengths_mm + legacy length_mm); первая — основная. */
export function productLengths(product: {
  lengths_mm?: number[] | null;
  length_mm?: number | null;
}): number[] {
  return normalizeLengths([...(product.lengths_mm ?? []), product.length_mm ?? undefined]);
}

export function entryForLength(
  dict: QuantityPerHangerDict | null | undefined,
  lengthMm: number,
): HangerQuantityValue | null {
  if (!dict) return null;
  const entry = dict[lengthKey(lengthMm)];
  return entry ?? null;
}

/** Эффективное значение записи: приоритет авто > ручное (#60). */
export function effectiveValue(entry: HangerQuantityValue | null): EffectiveHangerValue {
  if (!entry) return { value: null, source: null };
  if (entry.auto != null) return { value: entry.auto, source: "auto" };
  if (entry.manual != null) return { value: entry.manual, source: "manual" };
  return { value: null, source: null };
}

export function effectiveForLength(
  dict: QuantityPerHangerDict | null | undefined,
  lengthMm: number,
): EffectiveHangerValue {
  return effectiveValue(entryForLength(dict, lengthMm));
}

export type PrimaryHangerValue = EffectiveHangerValue & { lengthMm: number };

/**
 * Значение для основной (минимальной) длины: приоритет авто > ручное.
 * null — нет длин или нет ни одного значения.
 */
export function primaryHangerValue(product: {
  lengths_mm?: number[] | null;
  length_mm?: number | null;
  quantity_per_hanger?: QuantityPerHangerDict | null;
}): PrimaryHangerValue | null {
  const lengths = productLengths(product);
  if (lengths.length === 0) return null;
  const lengthMm = lengths[0];
  const effective = effectiveForLength(product.quantity_per_hanger ?? null, lengthMm);
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
