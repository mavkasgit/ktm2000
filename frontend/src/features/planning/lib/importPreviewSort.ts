/**
 * Сортировка строк превью импорта плана (чисто клиентская): числовые поля
 * сравниваются числами, списки кодов — по количеству, текстовые —
 * натуральным сравнением с учётом чисел в артикулах («ЮП-2» раньше «ЮП-10»).
 *
 * Ключи типизированы списком колонок шапки (`PlanImportPreviewTable`),
 * поэтому новая сортируемая колонка обязана попасть в `ImportPreviewSortKey`.
 */

import type { SortConfig } from "@/shared/hooks/useTableQueryEngine";
import { nextMultiSortConfigs } from "@/shared/lib/multiSort";

/** Колонки превью, по которым можно сортировать (заголовки таблицы). */
export type ImportPreviewSortKey =
  | "source_row_number"
  | "source_sku"
  | "quantity"
  | "source_name"
  | "route_name"
  | "errors"
  | "warnings";

export type ImportPreviewSortConfig = { key: ImportPreviewSortKey; dir: "asc" | "desc" };

export type ImportPreviewRow = Record<string, unknown>;

const STRING_COLLATOR = new Intl.Collator(["ru-RU", "en-US"], {
  sensitivity: "base",
  numeric: true,
});

/**
 * Цикл клика по шапке: нет сортировки → по убыванию → по возрастанию → нет.
 *
 * Сам цикл — не этот файл, а `nextMultiSortConfigs`: он уже отвечает за
 * клик по шапке на всех остальных экранах, и вторая копия процедуры
 * разошлась бы с первой при первой же правке. Здесь только проекция на
 * превью, где сортируется одна колонка, а не мультисортировка: клик по
 * другой колонке заменяет выбранную, а не добавляет ей приоритет.
 */
export function nextImportPreviewSortConfig(
  prev: ImportPreviewSortConfig | null,
  key: ImportPreviewSortKey,
): ImportPreviewSortConfig | null {
  const current: SortConfig<ImportPreviewSortKey>[] =
    prev && prev.key === key ? [{ field: prev.key, order: prev.dir }] : [];
  const [head] = nextMultiSortConfigs(current, key);
  return head ? { key: head.field, dir: head.order } : null;
}

/** Число из значения или null; массив — по первому числовому элементу. */
function toNumber(value: unknown): number | null {
  if (Array.isArray(value)) {
    for (const item of value) {
      const nested = toNumber(item);
      if (nested != null) return nested;
    }
    return null;
  }
  if (value == null || value === "") return null;
  const num = Number(value);
  return Number.isFinite(num) ? num : null;
}

/**
 * Номер строки файла — тот же источник, что и ячейка «Строка»: своё поле
 * строки, иначе `payload.row_numbers`, иначе `after_data.source_row_numbers`.
 */
function rowNumberValue(row: ImportPreviewRow): number | null {
  const own = toNumber(row.source_row_number);
  if (own != null) return own;
  const payload = (row.payload as Record<string, unknown> | null) ?? {};
  const fromPayload = toNumber(payload.row_numbers);
  if (fromPayload != null) return fromPayload;
  return toNumber((row.after_data as Record<string, unknown> | null)?.source_row_numbers);
}

/** «Ошибки»/«Предупр.» — массивы кодов: сравниваются по количеству, не по склейке. */
function codeCountValue(row: ImportPreviewRow, key: ImportPreviewSortKey): number {
  const after = (row.after_data as Record<string, unknown> | null) ?? {};
  const value = row[key] ?? after[key];
  if (Array.isArray(value)) return value.length;
  return toNumber(value) ?? 0;
}

function sortValue(row: ImportPreviewRow, key: ImportPreviewSortKey): number | string | null {
  if (key === "errors" || key === "warnings") return codeCountValue(row, key);
  if (key === "source_row_number") return rowNumberValue(row);
  const after = (row.after_data as Record<string, unknown> | null) ?? {};
  const value = after[key] ?? row[key];
  if (key === "quantity") return toNumber(value);
  return value == null ? "" : String(value);
}

/**
 * Порядок строк превью по выбранной колонке. Пустые значения (нет номера
 * строки, нет количества) уходят в конец независимо от направления — как
 * `NULLS LAST` в серверной сортировке позиций плана.
 */
export function sortImportPreviewRows<T extends ImportPreviewRow>(
  rows: readonly T[],
  sortConfig: ImportPreviewSortConfig | null,
): T[] {
  if (!sortConfig) return [...rows];
  const { key, dir } = sortConfig;
  return [...rows].sort((a, b) => {
    const aValue = sortValue(a, key);
    const bValue = sortValue(b, key);
    if (aValue == null && bValue == null) return 0;
    if (aValue == null) return 1;
    if (bValue == null) return -1;
    const cmp =
      typeof aValue === "number" && typeof bValue === "number"
        ? aValue - bValue
        : STRING_COLLATOR.compare(String(aValue), String(bValue));
    return dir === "asc" ? cmp : -cmp;
  });
}
