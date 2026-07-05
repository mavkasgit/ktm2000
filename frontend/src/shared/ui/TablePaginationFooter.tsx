import { ChevronLeft, ChevronRight } from "lucide-react";

import type { PageLimitOption } from "@/shared/hooks/usePaginatedTableQuery";

export interface TablePaginationFooterProps {
  page: number;
  totalPages: number;
  total: number;
  shownCount: number;
  limit: PageLimitOption;
  onPageChange: (page: number) => void;
  onLimitChange: (limit: PageLimitOption) => void;
  rangeLabel?: string;
  showLimitSelector?: boolean;
}

export function TablePaginationFooter({
  page,
  totalPages,
  total,
  shownCount,
  limit,
  onPageChange,
  onLimitChange,
  rangeLabel,
  showLimitSelector = true,
}: TablePaginationFooterProps) {
  const label =
    rangeLabel ?? `Показано ${shownCount} из ${total} записей`;

  return (
    <div className="flex items-center justify-between p-4 border-t border-slate-200 bg-slate-50">
      <div className="flex items-center gap-2 text-xs text-slate-500 font-medium">
        {totalPages > 1 && (
          <>
            <button
              type="button"
              onClick={() => onPageChange(Math.max(1, page - 1))}
              disabled={page === 1}
              className="p-1.5 rounded-lg border border-slate-200 bg-white hover:bg-slate-50 disabled:opacity-50 disabled:hover:bg-white transition-colors"
              aria-label="Предыдущая страница"
            >
              <ChevronLeft className="h-4 w-4" />
            </button>
            <span className="px-2">
              Страница <strong className="text-slate-700">{page}</strong> из{" "}
              <strong className="text-slate-700">{totalPages}</strong>
            </span>
            <button
              type="button"
              onClick={() => onPageChange(Math.min(totalPages, page + 1))}
              disabled={page === totalPages}
              className="p-1.5 rounded-lg border border-slate-200 bg-white hover:bg-slate-50 disabled:opacity-50 disabled:hover:bg-white transition-colors"
              aria-label="Следующая страница"
            >
              <ChevronRight className="h-4 w-4" />
            </button>
          </>
        )}
        <span className={totalPages > 1 ? "ml-4" : undefined}>{label}</span>
      </div>
      {showLimitSelector && (
        <div className="flex items-center gap-2 text-xs text-slate-500">
          <span>На странице:</span>
          <select
            value={limit}
            onChange={(e) => onLimitChange(Number(e.target.value) as PageLimitOption)}
            className="rounded-lg border border-slate-200 bg-white px-2 py-1 text-slate-700"
            aria-label="Количество записей на странице"
          >
            <option value={50}>50</option>
            <option value={100}>100</option>
            <option value={200}>200</option>
            <option value={500}>500</option>
          </select>
        </div>
      )}
    </div>
  );
}