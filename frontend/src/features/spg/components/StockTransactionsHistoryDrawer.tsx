import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { Loader2, Search, X } from "lucide-react";

import {
  Button,
  DataTableColumnHeader,
  DateRangePicker,
  Input,
  TableCornerResetCell,
  TableCornerResetHeader,
  TablePaginationFooter,
  DATA_TABLE_STYLES,
  type DateRangeValue,
} from "@/shared/ui";
import { useFilterableTable } from "@/shared/hooks/useFilterableTable";
import type { SortConfig } from "@/shared/hooks/useTableQueryEngine";
import { usePaginatedTableQuery } from "@/shared/hooks/usePaginatedTableQuery";
import {
  getStockTransactions,
  formatDimensionsLabel,
} from "@/shared/api/stock";
import type { StockTransactionsListResponse, StockTransactionsParams } from "@/shared/api/stock";
import { queryKeys } from "@/shared/api/queryKeys";
import { buildColumnApiParams, buildColumnFilterValues } from "@/shared/lib/columnSpecs";
import { useDebouncedValue } from "@/shared/lib/useDebouncedValue";
import { isFirstRowsLoad, keepPreviousDataForScope } from "@/shared/lib/tableQueryPlaceholder";
import { getAriaSort } from "@/shared/lib/multiSort";
import {
  buildTransactionSortParam,
  type TransactionSortField,
} from "@/shared/lib/stockSortParams";
import { getTxCellValue, transactionColumns } from "../lib/transactionColumns";

interface StockTransactionsHistoryDrawerProps {
  productId?: number;
  productSku?: string | null;
  locationId?: number;
  open: boolean;
  onOpenChange: (open: boolean) => void;
}


/**
 * Параметры колоночных фильтров, приведённые к контракту запроса.
 *
 * Обёртка нужна ради типов: `buildColumnApiParams` отдаёт `Record<string, string>`,
 * и спред такого объекта теряет конкретные ключи — после спреда TypeScript не
 * видел в запросе ни `reason`, ни `comment`, и фильтр по колонке уезжал в
 * `queryKey` как `undefined`, то есть два разных фильтра делили один кеш.
 * Колонки не перечисляются: они приходят из описания.
 */
function buildTxColumnApiParams(
  columnFilters: Partial<Record<TransactionSortField, Set<string>>>,
  columnSearchQueries: Partial<Record<TransactionSortField, string>>,
): Pick<
  StockTransactionsParams,
  "reason" | "from_location" | "to_location" | "quality_state" | "comment"
> {
  return buildColumnApiParams(columnFilters, columnSearchQueries, transactionColumns);
}

const headerCellClass = `${DATA_TABLE_STYLES.headerRow} ${DATA_TABLE_STYLES.headerCell}`;

/**
 * Свежие движения сверху. Тот же порядок, что и дефолт эндпоинта
 * (`DEFAULT_TRANSACTION_SORT`), но объявленный здесь: сброс возвращает его,
 * а не пустую сортировку, и он не считается активным фильтром.
 */
const TX_DEFAULT_SORT: SortConfig<TransactionSortField>[] = [{ field: "date", order: "desc" }];

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
  const debouncedSearch = useDebouncedValue(search);
  const tableScrollRef = useRef<HTMLDivElement>(null);
  const hasDateFilter = Boolean(dateRange.from || dateRange.to);

  const {
    bindColumn,
    columnFilters,
    columnSearchQueries,
    debouncedColumnSearchQueries,
    handleSort: applySort,
    sortConfigs,
    setSortConfigs,
    hasActiveFilters,
    resetAll: handleResetFilters,
    resetColumnFilters,
  } = useFilterableTable<TransactionSortField>({
    defaultSort: TX_DEFAULT_SORT,
    extraHasActive: hasDateFilter || search.trim().length > 0,
    onExtraReset: () => {
      setDateRange({ from: "", to: "" });
      setSearch("");
    },
  });

  const columnApiParams = useMemo(
    () => buildTxColumnApiParams(columnFilters, debouncedColumnSearchQueries),
    [columnFilters, debouncedColumnSearchQueries],
  );

  const sort = buildTransactionSortParam(sortConfigs);

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
      debouncedColumnSearchQueries,
      sortConfigs,
    ],
  });

  const handleSortChange = useCallback(
    (field: TransactionSortField) => {
      applySort(field);
      resetPage();
    },
    [applySort, resetPage],
  );



  useEffect(() => {
    if (open) return;
    setDateRange({ from: "", to: "" });
    setSearch("");
    setSortConfigs([...TX_DEFAULT_SORT]);
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
      sort,
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
      sort,
      limit,
      offset,
      columnApiParams,
    ],
  );

  // Дерево держится на смене страницы, фильтра и сортировки, но НЕ через смену
  // артикула или склада: они входят в ключ, и placeholder оставил бы проводки
  // прежнего товара в ящике нового (ADR-0044).
  const { data, isPending } = useQuery({
    queryKey: queryKeys.stock.transactions({
      productId,
      locationId,
      limit,
      offset,
      search: debouncedSearch || undefined,
      dateFrom: dateRange.from || undefined,
      dateTo: dateRange.to || undefined,
      sort: txQueryParams.sort,
      reason: txQueryParams.reason,
      from_location: txQueryParams.from_location,
      to_location: txQueryParams.to_location,
      quality_state: txQueryParams.quality_state,
      comment: txQueryParams.comment,
    }),
    queryFn: () => getStockTransactions(txQueryParams),
    enabled: open && productId !== undefined,
    placeholderData: keepPreviousDataForScope<StockTransactionsListResponse>(
      (key) => {
        const params = key[1] as { productId?: number; locationId?: number } | undefined;
        return `${params?.productId ?? ""}|${params?.locationId ?? ""}`;
      },
      `${productId ?? ""}|${locationId ?? ""}`,
    ),
  });

  const transactions = data?.transactions ?? [];
  const total = data?.total ?? 0;
  const totalPages = getTotalPages(total);

  // Значения для попаперов фильтра — из описания колонок: читатель значения
  // объявлен в самой колонке (`cellValue`), поэтому список и фильтр берут одно
  // значение (#322). Колонки без фильтра («Дата», «Кол-во») списка не собирают.
  const uniqueValues: Partial<Record<TransactionSortField, string[]>> = useMemo(
    () => buildColumnFilterValues(transactions, transactionColumns),
    [transactions],
  );

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

          {isFirstRowsLoad(isPending, transactions) ? (
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
                      {transactionColumns.map((column) => (
                        <th
                          key={column.id}
                          className={`${headerCellClass} ${column.headerClassName ?? "text-left"}`}
                          aria-sort={column.sortField ? getAriaSort(sortConfigs, column.sortField) : undefined}
                        >
                          <DataTableColumnHeader
                            column={column}
                            bindColumn={bindColumn}
                            values={column.filterField ? uniqueValues[column.filterField] : undefined}
                            currentSorts={sortConfigs}
                            onSortChange={handleSortChange}
                          />
                        </th>
                      ))}
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
                          {getTxCellValue(tx, "date")}
                        </td>
                        <td className="p-2 text-xs font-medium">
                          {getTxCellValue(tx, "reason")}
                        </td>
                        <td className="p-2 text-xs">{getTxCellValue(tx, "from")}</td>
                        <td className="p-2 text-xs">{getTxCellValue(tx, "to")}</td>
                        <td className="p-2 text-right font-mono text-xs whitespace-nowrap">
                          {getTxCellValue(tx, "quantity")}
                          {formatDimensionsLabel(tx.dimensions, tx.dimensions_label) !== "—" && (
                            <span className="ml-1 text-muted-foreground">
                              × {formatDimensionsLabel(tx.dimensions, tx.dimensions_label)}
                            </span>
                          )}
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