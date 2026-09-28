import { useCallback, useMemo, useState } from "react";
import {
  buildColumnFilterPredicate,
  hasActiveColumnFilters,
} from "@/shared/lib/columnFilterSearch";
import { useFlushableDebouncedValue } from "@/shared/lib/useDebouncedValue";

/**
 * Состояние фильтров колонок и пауза перед запросом.
 *
 * Текст в поповере фильтрует выборку на сервере, поэтому введённая строка —
 * это параметр запроса, а не только подсказка списка. Задерживать его нужно
 * здесь, а не на каждом экране: одиннадцать экранов собирают из этого
 * состояния ключ запроса, и своя пауза на каждом — это одиннадцать мест, где
 * её рано или поздно забудут (ADR-0044).
 *
 * Значение отдаётся в двух видах, и разница существенна:
 *
 * - `columnSearchQueries` — сырое, для поля, бейджа и клиентских предикатов:
 *   поле обязано отвечать на ввод сразу, иначе первое нажатие пропадает;
 * - `debouncedColumnSearchQueries` — для серверных параметров и для
 *   `resetPageDeps`, чтобы страница возвращалась на первую вместе с
 *   запросом, а не на каждое нажатие.
 *
 * Пауза одна на карту, а не на колонку: одновременно в поповере печатает один
 * человек, и сбрасывать чужую колонку ему не нужно.
 */
export function useSortableColumnFilters<Field extends string>() {
  const [columnFilters, setColumnFilters] = useState<Partial<Record<Field, Set<string>>>>({});
  const [columnSearchQueries, setColumnSearchQueries] = useState<Partial<Record<Field, string>>>({});
  const { value: debouncedColumnSearchQueries, flush: flushColumnSearchQueries } =
    useFlushableDebouncedValue(columnSearchQueries);

  const onColumnFilterChange = useCallback((field: Field, selected: Set<string>) => {
    setColumnFilters((prev) => ({ ...prev, [field]: selected }));
  }, []);

  const onColumnSearchChange = useCallback((field: Field, query: string) => {
    setColumnSearchQueries((prev) => ({ ...prev, [field]: query }));
  }, []);

  // Сброс не применяется через `flush`: он зовёт его в том же тике, что и
  // `setState`, и прочитал бы ещё не обновлённое значение — на экране мигнуло
  // бы старое. Пауза и так отпустит пустое значение через 300 мс, а сброс
  // снимает и бейдж, и текст сразу.
  const resetColumnFilters = useCallback(() => {
    setColumnFilters({});
    setColumnSearchQueries({});
  }, []);

  const hasActiveColumnFiltersState = useMemo(
    () => hasActiveColumnFilters(columnFilters, columnSearchQueries),
    [columnFilters, columnSearchQueries],
  );

  const buildFilterPredicate = useCallback(
    <T>(getCellValue: (row: T, field: Field) => string, omit: Field[] = []) => {
      const omitted = new Set(omit);
      const filters = Object.fromEntries(
        Object.entries(columnFilters).filter(([key]) => !omitted.has(key as Field)),
      ) as Partial<Record<Field, Set<string>>>;
      const searches = Object.fromEntries(
        Object.entries(columnSearchQueries).filter(([key]) => !omitted.has(key as Field)),
      ) as Partial<Record<Field, string>>;
      return buildColumnFilterPredicate({ columnFilters: filters, columnSearchQueries: searches, getCellValue });
    },
    [columnFilters, columnSearchQueries],
  );

  const bindColumn = useCallback(
    (field: Field) => ({
      searchQuery: columnSearchQueries[field] ?? "",
      selectedValues: columnFilters[field] ?? new Set<string>(),
      onSearchChange: onColumnSearchChange,
      onFilterChange: onColumnFilterChange,
      onApplySearch: flushColumnSearchQueries,
    }),
    [columnFilters, columnSearchQueries, onColumnSearchChange, onColumnFilterChange, flushColumnSearchQueries],
  );

  return {
    columnFilters,
    columnSearchQueries,
    debouncedColumnSearchQueries,
    flushColumnSearchQueries,
    onColumnFilterChange,
    onColumnSearchChange,
    bindColumn,
    buildFilterPredicate,
    hasActiveColumnFilters: hasActiveColumnFiltersState,
    resetColumnFilters,
    setColumnFilters,
    setColumnSearchQueries,
  };
}
