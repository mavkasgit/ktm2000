import { useEffect, useState } from "react";

export type PaginatedTableLimit = 50 | 100 | 200 | 500;
export type PageLimitOption = PaginatedTableLimit;

export interface UsePaginatedTableQueryOptions {
  initialPage?: number;
  initialLimit?: PaginatedTableLimit;
  /** When any dependency changes, page resets to 1. */
  resetPageDeps?: readonly unknown[];
  /** Alias for resetPageDeps (TransfersPage). */
  extraDeps?: readonly unknown[];
}

export function usePaginatedTableQuery(options: UsePaginatedTableQueryOptions = {}) {
  const {
    initialPage = 1,
    initialLimit = 50,
    resetPageDeps = [],
    extraDeps,
  } = options;

  const pageResetDeps = extraDeps ?? resetPageDeps;

  const [page, setPage] = useState(initialPage);
  const [limit, setLimit] = useState<PaginatedTableLimit>(initialLimit);
  const offset = (page - 1) * limit;

  useEffect(() => {
    setPage(1);
    // eslint-disable-next-line react-hooks/exhaustive-deps -- pageResetDeps is caller-controlled
  }, [limit, ...pageResetDeps]);

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
    offset,
    getTotalPages,
    getRangeLabel,
    totalPages: getTotalPages,
    rangeLabel: getRangeLabel,
    resetPage: () => setPage(1),
  };
}