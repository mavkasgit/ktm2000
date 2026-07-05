import { ChevronLeft, ChevronRight } from "lucide-react";

import type { PageLimitOption } from "@/shared/hooks/usePaginatedTableQuery";
import { PageLimitSelect } from "@/shared/ui/PageLimitSelect";

const MIN_PAGE_LIMIT = 50;

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
  limitOptions?: PageLimitOption[];
  /** Без внешней обёртки — для встраивания в составной футер (например, модалка). */
  embedded?: boolean;
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
  limitOptions,
  embedded = false,
}: TablePaginationFooterProps) {
  if (total <= MIN_PAGE_LIMIT) {
    return null;
  }

  const label =
    rangeLabel ?? `Показано ${shownCount} из ${total} записей`;

  const content = (
    <>
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
          <PageLimitSelect value={limit} onValueChange={onLimitChange} options={limitOptions} />
        </div>
      )}
    </>
  );

  if (embedded) {
    return (
      <div className="flex items-center justify-between flex-1 min-w-0 gap-4">
        {content}
      </div>
    );
  }

  return (
    <div className="flex items-center justify-between p-4 border-t border-slate-200 bg-slate-50">
      {content}
    </div>
  );
}