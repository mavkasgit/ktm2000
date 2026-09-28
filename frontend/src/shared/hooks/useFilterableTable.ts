import { useCallback, useMemo, useState } from "react";

import type { SortConfig } from "@/shared/hooks/useTableQueryEngine";
import { isDefaultSort, nextMultiSortConfigs } from "@/shared/lib/multiSort";

import { useSortableColumnFilters } from "./useSortableColumnFilters";

export interface UseFilterableTableOptions<SortField extends string> {
  extraHasActive?: boolean;
  onExtraReset?: () => void;
  /**
   * Порядок строк по умолчанию: сервер сортирует по нему, пока оператор не
   * выбрал колонку. Он не считается активными фильтрами, и сброс
   * возвращает его, а не пустоту.
   */
  defaultSort?: ReadonlyArray<SortConfig<SortField>>;
}

export function useFilterableTable<Field extends string, SortField extends string = Field>(
  options?: UseFilterableTableOptions<SortField>,
) {
  const columnFilters = useSortableColumnFilters<Field>();
  const defaultSort = options?.defaultSort;
  const [sortConfigs, setSortConfigs] = useState<SortConfig<SortField>[]>(
    () => (defaultSort ? [...defaultSort] : []),
  );

  const handleSort = useCallback((field: SortField) => {
    setSortConfigs((prev) => nextMultiSortConfigs(prev, field));
  }, []);
  const hasActiveFilters = useMemo(
    () =>
      columnFilters.hasActiveColumnFilters ||
      !isDefaultSort(sortConfigs, defaultSort) ||
      (options?.extraHasActive ?? false),
    [columnFilters.hasActiveColumnFilters, sortConfigs, defaultSort, options?.extraHasActive],
  );

  const resetAll = useCallback(() => {
    columnFilters.resetColumnFilters();
    setSortConfigs(defaultSort ? [...defaultSort] : []);
    options?.onExtraReset?.();
  }, [columnFilters.resetColumnFilters, defaultSort, options?.onExtraReset]);

  return {
    ...columnFilters,
    sortConfigs,
    setSortConfigs,
    handleSort,
    hasActiveFilters,
    resetAll,
  };
}