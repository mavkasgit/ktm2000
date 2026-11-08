import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { X } from "lucide-react";

import {
  Button,
  DataTableColumnHeader,
  DateRangePicker,
  FiltersPanel,
  TableCornerResetCell,
  TableCornerResetHeader,
  TablePaginationFooter,
  DATA_TABLE_STYLES,
  TABLE_ROW_DENSE,
  type DateRangeValue,
  type FiltersPanelField,
} from "@/shared/ui";
import { useFilterableTable } from "@/shared/hooks/useFilterableTable";
import type { SortConfig } from "@/shared/hooks/useTableQueryEngine";
import { usePaginatedTableQuery } from "@/shared/hooks/usePaginatedTableQuery";
import {
  getStockTransactions,
  formatDimensionsLabel,
} from "@/shared/api/stock";
import type {
  StockTransactionEntry,
  StockTransactionsListResponse,
  StockTransactionsParams,
} from "@/shared/api/stock";
import { ROW_TONE_STRIPE, ROW_TONE_TEXT, rowToneFill, type RowTone } from "@/shared/lib/rowTones";
import { cn } from "@/shared/utils/cn";
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

const headerCellClass = cn(
  DATA_TABLE_STYLES.headerRow,
  DATA_TABLE_STYLES.headerCell,
  TABLE_ROW_DENSE.headerCell,
);

/**
 * Тон строки движения — из общего словаря: брак читается тем же красным, что
 * и в остальных таблицах, остальные движения живут обычным тоном. Своей
 * палитры у ящика нет.
 */
function txRowTone(tx: StockTransactionEntry): RowTone {
  return tx.to_quality_state === "SCRAP" || tx.to_quality_state === "FINAL_SCRAP"
    ? "scrap"
    : "plain";
}

/** Колонок в таблице движений: семь плюс угол сброса фильтров. */
const COLUMN_COUNT = transactionColumns.length + 1;

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

  /**
   * Ряд фильтров — общий `FiltersPanel` (`compact`): поиск → период, в том же
   * порядке и с той же высотой, что на доске и в «Передачах». Своя вёрстка
   * ряда с `Input` и иконкой поиска давала третий вариант одного тулбара.
   */
  const filterFields: FiltersPanelField[] = [
    {
      kind: "search",
      key: "search",
      value: search,
      onChange: setSearch,
      placeholder: "Поиск по комментарию, причине, локациям…",
      layoutSpan: "min-w-[240px] flex-1 max-w-md",
    },
    {
      kind: "custom",
      key: "period",
      layoutSpan: "w-full sm:w-auto sm:min-w-[280px] max-w-md flex-shrink-0",
      node: (
        <DateRangePicker
          from={dateRange.from}
          to={dateRange.to}
          onChange={setDateRange}
          className="w-full"
          placeholder="Период"
          align="start"
        />
      ),
    },
  ];

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
          <FiltersPanel
            compact
            fields={filterFields}
            onReset={handleResetFilters}
            hasActiveFilters={hasActiveFilters}
          />

          <div className={DATA_TABLE_STYLES.container}>
            <div
              ref={tableScrollRef}
              className="overflow-auto"
              style={{ maxHeight: "70vh" }}
            >
              <table className="w-full border-separate border-spacing-0 text-sm">
                <thead>
                  <tr>
                    {transactionColumns.map((column) => (
                      <th
                        key={column.id}
                        className={cn(headerCellClass, column.headerClassName ?? "text-left")}
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
                  {isFirstRowsLoad(isPending, transactions) ? (
                    <tr>
                      <td
                        colSpan={COLUMN_COUNT}
                        className={cn(TABLE_ROW_DENSE.cell, "py-6 text-center text-sm text-muted-foreground")}
                      >
                        Загрузка…
                      </td>
                    </tr>
                  ) : transactions.length === 0 ? (
                    <tr>
                      <td
                        colSpan={COLUMN_COUNT}
                        className={cn(TABLE_ROW_DENSE.cell, "py-6 text-center text-sm text-muted-foreground")}
                      >
                        {hasActiveFilters
                          ? "Ничего не найдено по выбранным фильтрам"
                          : "Транзакции не найдены"}
                      </td>
                    </tr>
                  ) : (
                    transactions.map((tx) => {
                      const tone = txRowTone(tx);
                      return (
                        <tr
                          key={tx.id}
                          style={{ height: TABLE_ROW_DENSE.rowHeightPx }}
                          className={cn(rowToneFill(tone), ROW_TONE_TEXT[tone], "transition-colors")}
                        >
                          <td
                            className={cn(
                              TABLE_ROW_DENSE.cell,
                              ROW_TONE_STRIPE[tone],
                              "text-xs whitespace-nowrap",
                            )}
                          >
                            {getTxCellValue(tx, "date")}
                          </td>
                          <td className={cn(TABLE_ROW_DENSE.cell, "text-xs font-medium")}>
                            {getTxCellValue(tx, "reason")}
                          </td>
                          <td className={cn(TABLE_ROW_DENSE.cell, "text-xs")}>
                            {getTxCellValue(tx, "from")}
                          </td>
                          <td className={cn(TABLE_ROW_DENSE.cell, "text-xs")}>
                            {getTxCellValue(tx, "to")}
                          </td>
                          <td
                            className={cn(
                              TABLE_ROW_DENSE.cell,
                              "text-right font-mono text-xs whitespace-nowrap",
                            )}
                          >
                            {getTxCellValue(tx, "quantity")}
                            {formatDimensionsLabel(tx.dimensions, tx.dimensions_label) !== "—" && (
                              <span className="ml-1 text-muted-foreground">
                                × {formatDimensionsLabel(tx.dimensions, tx.dimensions_label)}
                              </span>
                            )}
                          </td>
                          <td className={cn(TABLE_ROW_DENSE.cell, "text-xs")}>
                            {getTxCellValue(tx, "quality")}
                          </td>
                          <td
                            className={cn(
                              TABLE_ROW_DENSE.cell,
                              "text-xs text-muted-foreground max-w-[150px] truncate",
                            )}
                          >
                            {getTxCellValue(tx, "comment")}
                          </td>
                          <TableCornerResetCell />
                        </tr>
                      );
                    })
                  )}
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
        </div>
      </div>
    </div>
  );
}