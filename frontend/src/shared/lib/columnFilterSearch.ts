import { normalizeText } from "./textNormalize";

export function matchesPartialSearch(haystack: string, query: string): boolean {
  const q = normalizeText(query.trim());
  if (!q) return true;
  return normalizeText(haystack).includes(q);
}

/** Lower rank = better match. Infinity = no match. */
export function rankPartialSearchMatch(label: string, query: string): number {
  const q = normalizeText(query.trim());
  if (!q) return 0;
  const normalized = normalizeText(label);
  if (normalized.startsWith(q)) return 0;
  const idx = normalized.indexOf(q);
  if (idx === -1) return Number.POSITIVE_INFINITY;
  return 1 + idx;
}

export function sortByPartialSearchMatch<T>(
  values: T[],
  query: string,
  getLabel: (value: T) => string,
): T[] {
  const q = query.trim();
  if (!q) return values;
  return [...values]
    .filter((v) => matchesPartialSearch(getLabel(v), q))
    .sort((a, b) => {
      const rankDiff = rankPartialSearchMatch(getLabel(a), q) - rankPartialSearchMatch(getLabel(b), q);
      if (rankDiff !== 0) return rankDiff;
      return getLabel(a).localeCompare(getLabel(b), "ru");
    });
}

/**
 * Индикатор «фильтры активны» и кнопка сброса: есть ли в таблице хоть
 * какой-нибудь выбранный фильтр или введённый поиск.
 *
 * Считается по состоянию таблицы, а не по тому, что уехало в запрос: выбор в
 * `clientOnly`-колонке (в том числе мультивыбор, ADR-0044) включает
 * индикатор, хотя `pickColumnApiValue` для неё вернёт `undefined`. Это
 * намеренно — сброс обязан убирать всё выбранное, а не только то, что сервер
 * понимает как параметр.
 */
export function hasActiveColumnFilters<Field extends string>(
  columnFilters: Partial<Record<Field, Set<string>>>,
  columnSearchQueries: Partial<Record<Field, string>>,
): boolean {
  const hasSetFilters = Object.values(columnFilters).some(
    (s): s is Set<string> => s instanceof Set && s.size > 0,
  );
  const hasSearchFilters = Object.values(columnSearchQueries).some(
    (q): q is string => typeof q === "string" && q.trim().length > 0,
  );
  return hasSetFilters || hasSearchFilters;
}

/**
 * Одно значение колонки для серверного параметра запроса (ILIKE-поиск или
 * точный выбор).
 *
 * Сервер принимает на колонку одно значение, поэтому в параметр превращается
 * только одиночный выбор: `size !== 1` → `undefined` — это граница контракта с
 * сервером, а не «фильтр выключен» (активность считает
 * `hasActiveColumnFilters`, ему всё равно, что уедет в запрос).
 *
 * Мультивыбор сюда по построению не попадает: он разрешён только у
 * `clientOnly`-колонок, чьи значения в запрос не уезжают
 * (`multiSelect = clientOnly === true` в `DataTableColumnHeader`, ADR-0044).
 */
export function pickColumnApiValue<T extends string>(
  columnFilters: Partial<Record<T, Set<string>>>,
  columnSearchQueries: Partial<Record<T, string>>,
  field: T,
  mapValue: (value: string) => string | undefined = (value) => value,
): string | undefined {
  const searchQuery = columnSearchQueries[field]?.trim();
  if (searchQuery) return mapValue(searchQuery);

  const selected = columnFilters[field];
  if (!selected || selected.size !== 1) return undefined;
  const [value] = selected;
  return mapValue(value);
}

/**
 * Одно выбранное значение колонки точного совпадения (габариты): поиск в
 * попапере игнорируется — он сужает список значений, но не фильтрует строки.
 *
 * Тот же одиночный контракт с сервером, что и у `pickColumnApiValue`:
 * больше одного значения передать некуда, поэтому `size !== 1` →
 * `undefined`, а активность состояния считает `hasActiveColumnFilters`.
 */
export function pickExactMatchColumnValue<T extends string>(
  columnFilters: Partial<Record<T, Set<string>>>,
  field: T,
): string | undefined {
  const selected = columnFilters[field];
  if (!selected || selected.size !== 1) return undefined;
  return [...selected][0];
}

export function buildColumnFilterPredicate<T, Field extends string>(opts: {
  columnFilters: Partial<Record<Field, Set<string>>>;
  columnSearchQueries: Partial<Record<Field, string>>;
  getCellValue: (row: T, field: Field) => string;
}): ((row: T) => boolean) | null {
  const { columnFilters, columnSearchQueries, getCellValue } = opts;
  if (!hasActiveColumnFilters(columnFilters, columnSearchQueries)) return null;

  return (row: T) => {
    const fields = new Set<Field>([
      ...(Object.keys(columnFilters) as Field[]),
      ...(Object.keys(columnSearchQueries) as Field[]),
    ]);

    for (const field of fields) {
      const search = columnSearchQueries[field]?.trim();
      const selected = columnFilters[field];
      const cellValue = getCellValue(row, field);

      if (search) {
        if (!matchesPartialSearch(cellValue, search)) return false;
        continue;
      }

      if (selected && selected.size > 0 && !selected.has(cellValue)) {
        return false;
      }
    }
    return true;
  };
}