import type { SortConfig } from "@/shared/hooks/useTableQueryEngine";

/**
 * Сколько колонок можно сортировать одновременно.
 *
 * Больше трёх шапка перестаёт читаться: бейджи приоритетов сливаются,
 * а строка `sort` в запросе раздувается. При попытке добавить четвёртую
 * снимается самая старая (приоритет 1) — оператор не упирается в
 * «ничего не происходит», а видит, что порядок изменился.
 */
export const MAX_SORT_FIELDS = 3;

/**
 * Click cycle for multi-sort: none -> desc (append with next priority) -> asc -> removed.
 */
export function nextMultiSortConfigs<Field extends string>(
  prev: SortConfig<Field>[],
  field: Field,
): SortConfig<Field>[] {
  const existing = prev.findIndex((s) => s.field === field);
  if (existing === -1) {
    return appendWithinLimit(prev, { field, order: "desc" });
  }

  const next = [...prev];
  if (next[existing].order === "desc") {
    next[existing] = { field, order: "asc" };
  } else {
    next.splice(existing, 1);
  }
  return next;
}

/**
 * Состояние сортировки колонки для `aria-sort` на `<th>` (ADR-0037, #285).
 *
 * Формула тривиальная, но она нужна каждой сортируемой таблице — а копия в
 * каждой шапке расходится с `nextMultiSortConfigs` в тот же день, когда
 * меняется цикл сортировки. `none` здесь не «нет атрибута»: на сортируемой
 * колонке это объявление «сортировка возможна, сейчас не выбрана», и его
 * отсутствие скринридер читает как «колонка не сортируется».
 */
export function getAriaSort<Field extends string>(
  currentSorts: ReadonlyArray<SortConfig<Field>>,
  field: Field,
): "none" | "ascending" | "descending" {
  const active = currentSorts.find((config) => config.field === field);
  if (!active) return "none";
  return active.order === "asc" ? "ascending" : "descending";
}

/** Добавляет сортировку в конец, вытесняя самую старую при переполнении. */
function appendWithinLimit<Field extends string>(
  prev: SortConfig<Field>[],
  config: SortConfig<Field>,
): SortConfig<Field>[] {
  if (prev.length < MAX_SORT_FIELDS) return [...prev, config];
  return [...prev.slice(prev.length - MAX_SORT_FIELDS + 1), config];
}

/**
 * Совпадает ли текущий порядок строк с заявленным по умолчанию.
 *
 * Экраны, у которых есть сортировка по умолчанию («сначала свежие»), не могут
 * считать её фильтром: иначе кнопка сброса висит на странице всегда. Каждый
 * такой экран сравнивал сортировку сам, и сравнение расходилось от экрана к
 * экрану. Порядок приоритетов тоже часть сравнения: `a, b` и `b, a` — разные
 * порядки строк, даже если набор колонок один.
 */
export function isDefaultSort<Field extends string>(
  current: ReadonlyArray<SortConfig<Field>>,
  defaultSort: ReadonlyArray<SortConfig<Field>> | undefined,
): boolean {
  if (defaultSort === undefined) return current.length === 0;
  if (current.length !== defaultSort.length) return false;
  return current.every((config, index) => {
    const expected = defaultSort[index];
    return expected !== undefined && config.field === expected.field && config.order === expected.order;
  });
}
