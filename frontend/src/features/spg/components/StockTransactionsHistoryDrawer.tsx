import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { Loader2, Search, X } from "lucide-react";

import {
  Button,
  DateRangePicker,
  Input,
  SortableFilterHeader,
  TableCornerResetCell,
  TableCornerResetHeader,
  TablePaginationFooter,
  DATA_TABLE_STYLES,
  type DateRangeValue,
} from "@/shared/ui";
import { useFilterableTable } from "@/shared/hooks/useFilterableTable";
import { usePaginatedTableQuery } from "@/shared/hooks/usePaginatedTableQuery";
import {
  getStockTransactions,
  formatBalanceQtyInteger,
  formatQualityStateLabel,
  formatStockReasonLabel,
} from "@/shared/api/stock";
import type { StockTransactionEntry, StockTransactionsParams } from "@/shared/api/stock";
import { queryKeys } from "@/shared/api/queryKeys";
import { pickColumnApiValue } from "@/shared/lib/columnFilterSearch";

interface StockTransactionsHistoryDrawerProps {
  productId?: number;
  productSku?: string | null;
  locationId?: number;
  open: boolean;
  onOpenChange: (open: boolean) => void;
}

type TransactionSortField = "date" | "reason" | "from" | "to" | "quantity" | "quality" | "comment";

function formatTxDate(createdAt: string | null): string {
  if (!createdAt) return "—";
  return new Date(createdAt).toLocaleString("ru-RU");
}

function formatTxQuality(tx: StockTransactionEntry): string {
  if (tx.from_quality_state !== tx.to_quality_state) {
    return `${formatQualityStateLabel(tx.from_quality_state)} → ${formatQualityStateLabel(tx.to_quality_state)}`;
  }
  return formatQualityStateLabel(tx.from_quality_state);
}

function getTxCellValue(tx: StockTransactionEntry, field: TransactionSortField): string {
  switch (field) {
    case "date":
      return formatTxDate(tx.created_at);
    case "reason":
      return formatStockReasonLabel(String(tx.reason), tx.source_ref);
    case "from":
      return tx.from_location_name || (tx.from_location_id ? `#${tx.from_location_id}` : "—");
    case "to":
      return tx.to_location_name || (tx.to_location_id ? `#${tx.to_location_id}` : "—");
    case "quantity":
      return formatBalanceQtyInteger(tx.quantity);
    case "quality":
      return formatTxQuality(tx);
    case "comment":
      return tx.comment || "—";
  }
}

function mapTxSortFieldToApi(field: TransactionSortField): string {
  switch (field) {
    case "date":
      return "created_at";
    case "from":
      return "from_location";
    case "to":
      return "to_location";
    case "quality":
      return "quality_state";
    default:
      return field;
  }
}

function extractQualityStateLabel(label: string): string | undefined {
  if (label === "—") return undefined;
  const part = label.split(" → ")[0]?.trim() ?? label;
  const normalized = part.toLowerCase();
  if (normalized === "годный") return "good";
  if (normalized === "брак") return "scrap";
  if (normalized === "окончательный брак") return "final_scrap";
  if (normalized === "переделка") return "rework";
  return part;
}

function buildTxColumnApiParams(
  columnFilters: Partial<Record<TransactionSortField, Set<string>>>,
  columnSearchQueries: Partial<Record<TransactionSortField, string>>,
): Pick<StockTransactionsParams, "reason" | "from_location" | "to_location" | "quality_state" | "comment"> {
  const params: Pick<
    StockTransactionsParams,
    "reason" | "from_location" | "to_location" | "quality_state" | "comment"
  > = {};

  const reason = pickColumnApiValue(columnFilters, columnSearchQueries, "reason", (v) =>
    v === "—" ? undefined : v,
  );
  if (reason) params.reason = reason;

  const fromLocation = pickColumnApiValue(columnFilters, columnSearchQueries, "from", (v) =>
    v === "—" ? undefined : v,
  );
  if (fromLocation) params.from_location = fromLocation;

  const toLocation = pickColumnApiValue(columnFilters, columnSearchQueries, "to", (v) =>
    v === "—" ? undefined : v,
  );
  if (toLocation) params.to_location = toLocation;

  const qualityState = pickColumnApiValue(
    columnFilters,
    columnSearchQueries,
    "quality",
    extractQualityStateLabel,
  );
  if (qualityState) params.quality_state = qualityState;

  const comment = pickColumnApiValue(columnFilters, columnSearchQueries, "comment", (v) =>
    v === "—" ? undefined : v,
  );
  if (comment) params.comment = comment;

  return params;
}

const headerCellClass = `${DATA_TABLE_STYLES.headerRow} ${DATA_TABLE_STYLES.headerCell}`;

export function StockTransactionsHistoryDrawer({
  productId,
  productSku,
  locationId,
  open,
  onOpenChange,
}: StockTransactionsHistoryDrawerProps) {
  const productLabel = productSku?.trim() || (productId !== undefined ? `#${productId}` : null);
  const [dateRange, setDateRange] = useState<DateRangeValue>({ from: "", to: "" });
  const [search, setSearch] = useState("");
  const [debouncedSearch, setDebouncedSearch] = useState("");
  const tableScrollRef = useRef<HTMLDivElement>(null);
  const hasDateFilter = Boolean(dateRange.from || dateRange.to);

  const {
    bindColumn,
    columnFilters,
    columnSearchQueries,
    sortConfigs,
    setSortConfigs,
    hasActiveFilters,
    resetAll: handleResetFilters,
    resetColumnFilters,
  } = useFilterableTable<TransactionSortField>({
    extraHasActive: hasDateFilter || search.trim().length > 0,
    onExtraReset: () => {
      setDateRange({ from: "", to: "" });
      setSearch("");
      setDebouncedSearch("");
    },
  });

  const columnApiParams = useMemo(
    () => buildTxColumnApiParams(columnFilters, columnSearchQueries),
    [columnFilters, columnSearchQueries],
  );

  const activeSort = sortConfigs[0];

  const {
    page,
    setPage,
    limit,
    setLimit,
    offset,
    getTotalPages,
    getRangeLabel,
    resetPage,
  } = usePaginatedTableQuery({
    resetPageDeps: [
      productId,
      locationId,
      debouncedSearch,
      dateRange.from,
      dateRange.to,
      columnFilters,
      columnSearchQueries,
      sortConfigs,
    ],
  });

  const handleSortChange = useCallback(
    (field: TransactionSortField) => {
      setSortConfigs((prev) => {
        const existing = prev.find((sort) => sort.field === field);
        if (!existing) {
          return [{ field, order: "desc" }];
        }
        return [{ field, order: existing.order === "asc" ? "desc" : "asc" }];
      });
      resetPage();
    },
    [resetPage, setSortConfigs],
  );

  useEffect(() => {
    const timer = window.setTimeout(() => setDebouncedSearch(search), 300);
    return () => window.clearTimeout(timer);
  }, [search]);

  useEffect(() => {
    if (open) return;
    setDateRange({ from: "", to: "" });
    setSearch("");
    setDebouncedSearch("");
    setSortConfigs([]);
    resetColumnFilters();
    resetPage();
    // Reset only when the drawer closes; avoid unstable callback deps while closed.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [open]);

  const txQueryParams = useMemo(
    () => ({
      product_id: productId,
      location_id: locationId,
      search: debouncedSearch.trim() || undefined,
      date_from: dateRange.from || undefined,
      date_to: dateRange.to || undefined,
      sort_by: activeSort ? mapTxSortFieldToApi(activeSort.field) : "created_at",
      sort_order: activeSort?.order ?? "desc",
      limit,
      offset,
      ...columnApiParams,
    }),
    [
      productId,
      locationId,
      debouncedSearch,
      dateRange.from,
      dateRange.to,
      activeSort,
      limit,
      offset,
      columnApiParams,
    ],
  );

  const { data, isLoading } = useQuery({
    queryKey: queryKeys.stock.transactions({
      productId,
      locationId,
      limit,
      offset,
      search: debouncedSearch || undefined,
      dateFrom: dateRange.from || undefined,
      dateTo: dateRange.to || undefined,
      sort_by: txQueryParams.sort_by,
      sort_order: txQueryParams.sort_order,
      reason: txQueryParams.reason as string | undefined,
      from_location: txQueryParams.from_location,
      to_location: txQueryParams.to_location,
      quality_state: txQueryParams.quality_state,
      comment: txQueryParams.comment,
    }),
    queryFn: () => getStockTransactions(txQueryParams),
    enabled: open && productId !== undefined,
  });

  const transactions = data?.transactions ?? [];
  const total = data?.total ?? 0;
  const totalPages = getTotalPages(total);

  const uniqueValues = useMemo(() => ({
    date: [...new Set(transactions.map((tx) => getTxCellValue(tx, "date")))].sort((a, b) =>
      a.localeCompare(b, "ru"),
    ),
    reason: [...new Set(transactions.map((tx) => getTxCellValue(tx, "reason")))].sort((a, b) =>
      a.localeCompare(b, "ru"),
    ),
    from: [...new Set(transactions.map((tx) => getTxCellValue(tx, "from")))].sort((a, b) =>
      a.localeCompare(b, "ru"),
    ),
    to: [...new Set(transactions.map((tx) => getTxCellValue(tx, "to")))].sort((a, b) =>
      a.localeCompare(b, "ru"),
    ),
    quantity: [...new Set(transactions.map((tx) => getTxCellValue(tx, "quantity")))].sort(
      (a, b) => (Number.parseFloat(a) || 0) - (Number.parseFloat(b) || 0),
    ),
    quality: [...new Set(transactions.map((tx) => getTxCellValue(tx, "quality")))].sort((a, b) =>
      a.localeCompare(b, "ru"),
    ),
    comment: [...new Set(transactions.map((tx) => getTxCellValue(tx, "comment")))].sort((a, b) =>
      a.localeCompare(b, "ru"),
    ),
  }), [transactions]);

  if (!open) return null;

  return (
    <div className="fixed inset-0 z-50 flex justify-end">
      <div className="fixed inset-0 bg-black/30" onClick={() => onOpenChange(false)} />
      <div className="relative w-full max-w-3xl bg-background shadow-xl border-l overflow-y-auto animate-in slide-in-from-right">
        <div className="sticky top-0 bg-background border-b z-10 px-4 py-3 flex items-center justify-between gap-3">
          <h2 className="text-lg font-semibold min-w-0 truncate">
            {productLabel
              ? <>История движения по артикулу <span className="text-primary">{productLabel}</span></>
              : "История движения"}
          </h2>
          <Button variant="ghost" size="icon" onClick={() => onOpenChange(false)}>
            <X className="h-5 w-5" />
          </Button>
        </div>

        <div className="p-4 space-y-4">
          <div className="flex flex-col sm:flex-row gap-2">
            <div className="relative flex-1 max-w-md">
              <Search className="absolute left-3 top-1/2 -translate-y-1/2 h-4 w-4 text-muted-foreground" />
              <Input
                placeholder="Поиск по комментарию, причине, локациям…"
                value={search}
                onChange={(e) => setSearch(e.target.value)}
                className="pl-9"
              />
              {search && (
                <button
                  type="button"
                  onClick={() => setSearch("")}
                  className="absolute right-3 top-1/2 -translate-y-1/2"
                  aria-label="Очистить поиск"
                >
                  <X className="h-4 w-4 text-muted-foreground" />
                </button>
              )}
            </div>
            <DateRangePicker
              from={dateRange.from}
              to={dateRange.to}
              onChange={setDateRange}
              className="w-full sm:w-auto sm:min-w-[280px] max-w-md"
              placeholder="Период"
              align="start"
            />
          </div>

          {isLoading ? (
            <div className="flex items-center justify-center py-12">
              <Loader2 className="h-6 w-6 animate-spin text-muted-foreground" />
            </div>
          ) : total === 0 ? (
            <div className="text-center py-12 text-sm text-muted-foreground border rounded-lg border-dashed">
              Транзакции не найдены
            </div>
          ) : (
            <div className={DATA_TABLE_STYLES.container}>
              <div
                ref={tableScrollRef}
                className="overflow-auto"
                style={{ maxHeight: "70vh" }}
              >
                <table className="w-full text-sm">
                  <thead>
                    <tr>
                      <th className={`${headerCellClass} p-0`}>
                        <SortableFilterHeader
                          field="date"
                          label="Дата"
                          currentSorts={sortConfigs}
                          onSortChange={handleSortChange}
                          values={uniqueValues.date}
                          {...bindColumn("date")}
                        />
                      </th>
                      <th className={`${headerCellClass} p-0`}>
                        <SortableFilterHeader
                          field="reason"
                          label="Причина"
                          currentSorts={sortConfigs}
                          onSortChange={handleSortChange}
                          values={uniqueValues.reason}
                          {...bindColumn("reason")}
                        />
                      </th>
                      <th className={`${headerCellClass} p-0`}>
                        <SortableFilterHeader
                          field="from"
                          label="Откуда"
                          currentSorts={sortConfigs}
                          onSortChange={handleSortChange}
                          values={uniqueValues.from}
                          {...bindColumn("from")}
                        />
                      </th>
                      <th className={`${headerCellClass} p-0`}>
                        <SortableFilterHeader
                          field="to"
                          label="Куда"
                          currentSorts={sortConfigs}
                          onSortChange={handleSortChange}
                          values={uniqueValues.to}
                          {...bindColumn("to")}
                        />
                      </th>
                      <th className={`${headerCellClass} p-0 text-right`}>
                        <SortableFilterHeader
                          field="quantity"
                          label="Кол-во"
                          currentSorts={sortConfigs}
                          onSortChange={handleSortChange}
                          values={uniqueValues.quantity}
                          {...bindColumn("quantity")}
                        />
                      </th>
                      <th className={`${headerCellClass} p-0`}>
                        <SortableFilterHeader
                          field="quality"
                          label="Качество"
                          currentSorts={sortConfigs}
                          onSortChange={handleSortChange}
                          values={uniqueValues.quality}
                          {...bindColumn("quality")}
                        />
                      </th>
                      <th className={`${headerCellClass} p-0`}>
                        <SortableFilterHeader
                          field="comment"
                          label="Комментарий"
                          currentSorts={sortConfigs}
                          onSortChange={handleSortChange}
                          values={uniqueValues.comment}
                          {...bindColumn("comment")}
                        />
                      </th>
                      <TableCornerResetHeader
                        hasActiveFilters={hasActiveFilters}
                        onReset={handleResetFilters}
                        dataTableHeader
                      />
                    </tr>
                  </thead>
                  <tbody>
                    {transactions.length === 0 ? (
                      <tr>
                        <td colSpan={8} className="p-8 text-center text-sm text-muted-foreground">
                          Ничего не найдено по выбранным фильтрам
                        </td>
                      </tr>
                    ) : (
                    transactions.map((tx) => (
                      <tr key={tx.id} className="border-b hover:bg-muted/30">
                        <td className="p-2 text-xs whitespace-nowrap">
                          {formatTxDate(tx.created_at)}
                        </td>
                        <td className="p-2 text-xs font-medium">
                          {getTxCellValue(tx, "reason")}
                        </td>
                        <td className="p-2 text-xs">{getTxCellValue(tx, "from")}</td>
                        <td className="p-2 text-xs">{getTxCellValue(tx, "to")}</td>
                        <td className="p-2 text-right font-mono text-xs">
                          {getTxCellValue(tx, "quantity")}
                        </td>
                        <td className="p-2 text-xs">{getTxCellValue(tx, "quality")}</td>
                        <td className="p-2 text-xs text-muted-foreground max-w-[150px] truncate">
                          {getTxCellValue(tx, "comment")}
                        </td>
                        <TableCornerResetCell />
                      </tr>
                    )))}
                  </tbody>
                </table>
              </div>
              <TablePaginationFooter
                page={page}
                totalPages={totalPages}
                total={total}
                shownCount={transactions.length}
                limit={limit}
                onPageChange={setPage}
                onLimitChange={setLimit}
                rangeLabel={getRangeLabel(transactions.length, total)}
              />
            </div>
          )}
        </div>
      </div>
    </div>
  );
}