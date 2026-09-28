import { useCallback, useEffect, useMemo, useState } from "react";
import { useQuery } from "@tanstack/react-query";

import {
  formatQualityStateLabel,
  formatDimensionsLabel,
  getStockBalances,
} from "@/shared/api/stock";
import type { StockBalanceEntry } from "@/shared/api/stock";
import { queryKeys } from "@/shared/api/queryKeys";
import { DataTableColumnHeader } from "./DataTableColumnHeader";
import { TablePanelHeader } from "./TablePanelHeader";
import { TableCornerResetCell, TableCornerResetHeader } from "./TableCornerResetHeader";
import { TablePaginationFooter } from "./TablePaginationFooter";
import { DATA_TABLE_STYLES } from "@/shared/lib/dataTableStyles";
import { useFilterableTable } from "@/shared/hooks/useFilterableTable";
import { usePaginatedTableQuery } from "@/shared/hooks/usePaginatedTableQuery";
import { buildColumnApiParams } from "@/shared/lib/columnSpecs";
import { RouteStepsDisplay } from "./RouteStepsDisplay";

import { buildBalanceSortParam, type BalanceSortField } from "@/shared/lib/stockSortParams";
import { stockBalanceColumns } from "@/shared/lib/stockBalanceColumns";
import { useDebouncedValue } from "@/shared/lib/useDebouncedValue";
import { fmtQty } from "@/shared/lib/quantityFormat";

function getBalanceOperationsLabel(balance: StockBalanceEntry): string {
  if (balance.completed_stages?.length) {
    return balance.completed_stages.map((stage) => stage.operation_name).join(", ");
  }
  return "—";
}

function getBalanceCellValue(balance: StockBalanceEntry, field: BalanceSortField): string {
  switch (field) {
    case "sku":
      return balance.product_sku || `#${balance.product_id}`;
    case "quantity":
      return fmtQty(balance.balance_qty);
    case "operations":
      return getBalanceOperationsLabel(balance);
    case "quality":
      return formatQualityStateLabel(balance.quality_state);
    case "location":
      return balance.location_name || `#${balance.location_id}`;
  }
}

function buildBalanceColumnApiParams(
  columnFilters: Partial<Record<BalanceSortField, Set<string>>>,
  columnSearchQueries: Partial<Record<BalanceSortField, string>>,
): Record<string, string> {
  return buildColumnApiParams(columnFilters, columnSearchQueries, stockBalanceColumns);
}



export interface StockBalancesPanelProps {
  locationId?: number;
  locationIds?: number[];
  searchQuery?: string;
  /** Сброс внешнего поиска (глобальный searchQuery на странице) при reset в шапке таблицы */
  onSearchQueryReset?: () => void;
  onSelectProduct: (productId: number) => void;
  onShowHistory: (productId: number, productSku?: string | null) => void;
  /** Скрыть колонку «Участок» — удобно, когда остатки уже отфильтрованы по одному участку */
  hideLocationColumn?: boolean;
  title?: string;
  enabled?: boolean;
}

const headerCellClass = `${DATA_TABLE_STYLES.headerRow} ${DATA_TABLE_STYLES.headerCell}`;

export function StockBalancesPanel({
  locationId,
  locationIds,
  searchQuery = "",
  onSearchQueryReset,
  onSelectProduct,
  onShowHistory,
  hideLocationColumn = false,
  title = "Наличие на участках",
  enabled = true,
}: StockBalancesPanelProps) {
  const [isExpanded, setIsExpanded] = useState(true);
  const debouncedSearch = useDebouncedValue(searchQuery);
  const {
    bindColumn,
    columnFilters,
    columnSearchQueries,
    sortConfigs,
    handleSort: applySort,
    hasActiveFilters,
    resetAll: handleResetFilters,
  } = useFilterableTable<BalanceSortField>({
    extraHasActive: searchQuery.trim().length > 0,
    onExtraReset: onSearchQueryReset,
  });

  const columnApiParams = useMemo(
    () => buildBalanceColumnApiParams(columnFilters, columnSearchQueries),
    [columnFilters, columnSearchQueries],
  );

  const sort = buildBalanceSortParam(sortConfigs);
  const normalizedLocationIds = useMemo(
    () => (locationIds?.length ? [...locationIds].sort((a, b) => a - b) : undefined),
    [locationIds],
  );

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
      locationId,
      normalizedLocationIds,
      debouncedSearch,
      columnFilters,
      columnSearchQueries,
      sortConfigs,
    ],
  });

  const handleSortChange = useCallback(
    (field: BalanceSortField) => {
      applySort(field);
      resetPage();
    },
    [applySort, resetPage],
  );



  const balanceQueryParams = useMemo(
    () => ({
      location_id: locationId,
      location_ids: normalizedLocationIds,
      search: debouncedSearch.trim() || undefined,
      sort,
      limit,
      offset,
      ...columnApiParams,
    }),
    [
      locationId,
      normalizedLocationIds,
      debouncedSearch,
      sort,
      limit,
      offset,
      columnApiParams,
    ],
  );

  const { data, isLoading } = useQuery({
    queryKey: queryKeys.stock.balances({
      locationId,
      locationIds: normalizedLocationIds,
      search: debouncedSearch.trim() || undefined,
      limit,
      offset,
      sort: balanceQueryParams.sort,
      sku: columnApiParams.sku,
      quantity: columnApiParams.quantity,
      quality: columnApiParams.quality,
      location: columnApiParams.location,
      operations: columnApiParams.operations,
    }),
    queryFn: () => getStockBalances(balanceQueryParams),
    enabled,
  });

  const balances = data?.balances ?? [];
  const total = data?.total ?? 0;
  const totalPages = getTotalPages(total);

  const uniqueValues: Partial<Record<BalanceSortField, string[]>> = useMemo(() => ({
    sku: [...new Set(balances.map((b) => getBalanceCellValue(b, "sku")))].sort((a, b) =>
      a.localeCompare(b, "ru"),
    ),
    quantity: [...new Set(balances.map((b) => getBalanceCellValue(b, "quantity")))].sort(
      (a, b) => (Number.parseFloat(a) || 0) - (Number.parseFloat(b) || 0),
    ),
    operations: [...new Set(balances.map((b) => getBalanceOperationsLabel(b)))].sort((a, b) =>
      a.localeCompare(b, "ru"),
    ),
    quality: [...new Set(balances.map((b) => getBalanceCellValue(b, "quality")))].sort((a, b) =>
      a.localeCompare(b, "ru"),
    ),
    location: [...new Set(balances.map((b) => getBalanceCellValue(b, "location")))].sort((a, b) =>
      a.localeCompare(b, "ru"),
    ),
  }), [balances]);

  const columnCount = hideLocationColumn ? 7 : 8;

  const handlePanelReset = useCallback(() => {
    handleResetFilters();
    resetPage();
  }, [handleResetFilters, resetPage]);

  const hasTableFilters =
    hasActiveFilters || sortConfigs.length > 0 || debouncedSearch.trim().length > 0;

  return (
    <div className="space-y-3">
      <TablePanelHeader
        title={title}
        countLabel={`(${balances.length} из ${total})`}
        expanded={isExpanded}
        onToggleExpanded={() => setIsExpanded(!isExpanded)}
      />

      {isExpanded && (
        <>
          {isLoading ? (
            <p className="text-sm text-muted-foreground py-4 text-center">Загрузка остатков...</p>
          ) : total === 0 ? (
            <div className="text-center py-8 text-sm text-muted-foreground border rounded-lg border-dashed">
              {hasTableFilters ? "Ничего не найдено по выбранным фильтрам" : "Записей о наличии нет"}
            </div>
          ) : (
            <div className={DATA_TABLE_STYLES.container}>
              <div className="overflow-auto" style={{ maxHeight: "70vh" }}>
                <table className="w-full text-sm text-left">
                  <thead>
                    <tr>
                      {stockBalanceColumns.map((column) => {
                        // Колонка «Участок» скрыта, когда панель показывает
                        // остатки по заводу: участка в такой строке нет.
                        if (column.hideWhenNoLocation && hideLocationColumn) return null;
                        return (
                          <th
                            key={column.id}
                            className={`${headerCellClass} ${column.filterField ? "p-0" : ""} ${column.headerClassName ?? ""}`}
                          >
                            <DataTableColumnHeader
                              column={column}
                              bindColumn={bindColumn}
                              values={column.filterField ? uniqueValues[column.filterField] : undefined}
                              currentSorts={sortConfigs}
                              onSortChange={handleSortChange}
                            />
                          </th>
                        );
                      })}
                      <th className={headerCellClass}>
                        Действия
                      </th>
                      <TableCornerResetHeader
                        hasActiveFilters={hasTableFilters}
                        onReset={handlePanelReset}
                        dataTableHeader
                      />
                    </tr>
                  </thead>
                  <tbody>
                    {balances.length === 0 ? (
                      <tr>
                        <td
                          colSpan={columnCount}
                          className="p-8 text-center text-sm text-muted-foreground"
                        >
                          Ничего не найдено по выбранным фильтрам
                        </td>
                      </tr>
                    ) : (
                    balances.map((b) => (
                      <tr key={b.id} className="border-b hover:bg-muted/30">
                        <td className="p-2">
                          <button
                            type="button"
                            className="font-medium hover:text-primary transition-colors cursor-pointer"
                            onClick={() => onSelectProduct(b.product_id)}
                            title="Показать детальные остатки"
                          >
                            {b.product_sku || `#${b.product_id}`}
                          </button>
                        </td>
                        <td className="p-2 font-semibold font-mono">
                          {fmtQty(b.balance_qty)}
                        </td>
                        <td className="p-2 text-xs whitespace-nowrap">
                          {formatDimensionsLabel(b.dimensions, b.dimensions_label)}
                        </td>
                        <td className="p-2 max-w-[280px]">
                          {b.completed_stages && b.completed_stages.length > 0 ? (
                            <RouteStepsDisplay steps={b.completed_stages} compact showIcons={false} />
                          ) : (
                            <span className="text-xs text-muted-foreground">—</span>
                          )}
                        </td>
                        <td className="p-2">
                          <span className="text-xs font-medium text-muted-foreground">
                            {formatQualityStateLabel(b.quality_state)}
                          </span>
                        </td>
                        {!hideLocationColumn && (
                          <td className="p-2 text-xs">
                            {b.location_name || `#${b.location_id}`}
                          </td>
                        )}
                        <td className="p-2">
                          <button
                            type="button"
                            className="text-xs text-muted-foreground hover:text-primary cursor-pointer"
                            onClick={() => onShowHistory(b.product_id, b.product_sku)}
                          >
                            История
                          </button>
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
                shownCount={balances.length}
                limit={limit}
                onPageChange={setPage}
                onLimitChange={setLimit}
                rangeLabel={getRangeLabel(balances.length, total)}
              />
            </div>
          )}
        </>
      )}
    </div>
  );
}