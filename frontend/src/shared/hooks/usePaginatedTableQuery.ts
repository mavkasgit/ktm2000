import { useCallback, useEffect, useState } from "react";

export type PaginatedTableLimit = 50 | 100 | 200 | 500;
export type PageLimitOption = PaginatedTableLimit;

const DEFAULT_LIMIT_OPTIONS: readonly PaginatedTableLimit[] = [50, 100, 200, 500];

function resolveInitialLimit(
  initialLimit: PaginatedTableLimit,
  limitOptions: readonly PaginatedTableLimit[],
): PaginatedTableLimit {
  if (limitOptions.includes(initialLimit)) {
    return initialLimit;
  }
  return limitOptions[limitOptions.length - 1]!;
}

export interface UsePaginatedTableQueryOptions {
  initialPage?: number;
  initialLimit?: PaginatedTableLimit;
  limitOptions?: readonly PaginatedTableLimit[];
  /**
   * Что сбрасывает страницу на первую. Один список: второй параметр с тем же
   * смыслом (`extraDeps`) жил рядом и использовался одним экраном, поэтому
   * «от чего сбрасывается страница» приходилось искать по двум полям.
   */
  resetPageDeps?: readonly unknown[];
}

export function usePaginatedTableQuery(options: UsePaginatedTableQueryOptions = {}) {
  const {
    initialPage = 1,
    initialLimit = 50,
    limitOptions = DEFAULT_LIMIT_OPTIONS,
    resetPageDeps = [],
  } = options;

  const [page, setPage] = useState(initialPage);

  const [limit, setLimit] = useState<PaginatedTableLimit>(() =>
    resolveInitialLimit(initialLimit, limitOptions),
  );
  const offset = (page - 1) * limit;

  useEffect(() => {
    setPage(1);
    // eslint-disable-next-line react-hooks/exhaustive-deps -- pageResetDeps is caller-controlled
  }, [limit, ...resetPageDeps]);

  const resetPage = useCallback(() => {
    setPage(1);
  }, []);

  const getTotalPages = (total: number) => Math.max(1, Math.ceil(total / limit));

  const getRangeLabel = (
    shownCount: number,
    total: number,
    opts?: { onPage?: boolean },
  ) => {
    if (opts?.onPage) {
      return `Показано ${shownCount} на странице из ${total} записей`;
    }
    return `Показано ${shownCount} из ${total} записей`;
  };

  return {
    page,
    setPage,
    limit,
    setLimit,
    limitOptions,
    offset,
    getTotalPages,
    getRangeLabel,
    resetPage,
  };
}