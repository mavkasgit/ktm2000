import { useCallback, useEffect, useMemo, useState } from "react";
import { useQuery } from "@tanstack/react-query";

import {
  formatQualityStateLabel,
  formatDimensionsLabel,
  formatCompletedOperationsLabel,
  getStockBalances,
} from "@/shared/api/stock";
import type { StockBalanceEntry, StockBalancesListResponse } from "@/shared/api/stock";
import { isFirstRowsLoad, keepPreviousDataForScope } from "@/shared/lib/tableQueryPlaceholder";
import { queryKeys } from "@/shared/api/queryKeys";
import { DataTableColumnHeader } from "./DataTableColumnHeader";
import { TablePanelHeader } from "./TablePanelHeader";
import { TableCornerResetCell, TableCornerResetHeader } from "./TableCornerResetHeader";
import { TablePaginationFooter } from "./TablePaginationFooter";
import { DATA_TABLE_STYLES, TABLE_ROW_DENSE } from "@/shared/lib/dataTableStyles";
import { TABLE_ROW_STYLES } from "@/shared/lib/tableRowStyles";
import { cn } from "@/shared/utils/cn";
import { useFilterableTable } from "@/shared/hooks/useFilterableTable";
import { usePaginatedTableQuery } from "@/shared/hooks/usePaginatedTableQuery";
import { buildColumnApiParams } from "@/shared/lib/columnSpecs";
import { getAriaSort } from "@/shared/lib/multiSort";
import { RouteStepsDisplay } from "./RouteStepsDisplay";

import { buildBalanceSortParam, type BalanceSortField } from "@/shared/lib/stockSortParams";
import { stockBalanceColumns } from "@/shared/lib/stockBalanceColumns";
import { useDebouncedValue } from "@/shared/lib/useDebouncedValue";
import { fmtQty, toQtyInteger } from "@/shared/lib/quantityFormat";
import { Badge } from "./badge";
import { ChevronDown, ChevronRight } from "lucide-react";

function getBalanceOperationsLabel(balance: StockBalanceEntry): string {
  return formatCompletedOperationsLabel(balance.completed_operations, balance.completed_stages);
}

/**
 * Ключ группы остатков — артикул. Остатки одного артикула приходят несколькими
 * строками (участок, качество, размеры, операции), и оператору нужен один
 * артикул с итогом, а не список строк, где артикул повторяется.
 */
function balanceArticleKey(balance: StockBalanceEntry): string {
  return balance.product_sku || `#${balance.product_id}`;
}

/** Сводка группы: то, что читается в свёрнутой строке-итоге. */
type BalanceGroup = {
  key: string;
  sku: string;
  rows: StockBalanceEntry[];
  /** Сумма количеств строк группы. */
  totalQty: number;
  /** Общее значение колонки у всех строк, иначе «—»: у группы не одно значение. */
  dimensionsLabel: string;
  operationsLabel: string;
  locationLabel: string;
  /**
   * Качество: один статус — его подпись, разные — раскладка «Годный 2 · Брак 1».
   * Раскладка, а не «—»: свёрнутая группа прячет брак, и итог обязан его назвать.
   */
  qualityLabel: string;
};

const GROUP_MIXED_VALUE = "—";

/** Одно значение на все строки — или «—»: у группы разные значения. */
function uniformLabel(
  rows: StockBalanceEntry[],
  pick: (balance: StockBalanceEntry) => string,
): string {
  const first = pick(rows[0]);
  return rows.every((row) => pick(row) === first) ? first : GROUP_MIXED_VALUE;
}

function qualitySummary(rows: StockBalanceEntry[]): string {
  const counts = new Map<string, number>();
  for (const row of rows) {
    const label = formatQualityStateLabel(row.quality_state);
    counts.set(label, (counts.get(label) ?? 0) + 1);
  }
  if (counts.size === 1) return [...counts.keys()][0];
  return [...counts.entries()].map(([label, count]) => `${label} ${count}`).join(" · ");
}

/**
 * Подсветка итога качества: свёрнутая группа прячет свои строки, поэтому брак
 * в ней обязан читаться в итоге — цветом, а не только словом.
 */
function qualitySummaryClass(rows: StockBalanceEntry[]): string {
  const states = rows.map((row) => row.quality_state.toUpperCase());
  if (states.some((state) => state === "SCRAP" || state === "FINAL_SCRAP")) {
    return "text-red-600 dark:text-red-400 font-medium";
  }
  if (states.some((state) => state === "REWORK")) {
    return "text-amber-700 dark:text-amber-400 font-medium";
  }
  return "text-muted-foreground";
}

/**
 * Группы остатков по артикулу — по всей отданной странице, а не по соседним
 * строкам: сортировка серверная, и при сортировке по количеству строки одного
 * артикула стоят вразброс, но группой остаются. Порядок групп — по первому
 * появлению артикула в ответе, то есть по тому же порядку, что видит оператор.
 */
function buildBalanceGroups(balances: StockBalanceEntry[]): BalanceGroup[] {
  const groups = new Map<string, BalanceGroup>();
  for (const balance of balances) {
    const key = balanceArticleKey(balance);
    const existing = groups.get(key);
    if (existing) {
      existing.rows.push(balance);
      existing.totalQty += toQtyInteger(balance.balance_qty);
      continue;
    }
    groups.set(key, {
      key,
      sku: key,
      rows: [balance],
      totalQty: toQtyInteger(balance.balance_qty),
      dimensionsLabel: "",
      operationsLabel: "",
      locationLabel: "",
      qualityLabel: "",
    });
  }
  return [...groups.values()].map((group) => ({
    ...group,
    dimensionsLabel: uniformLabel(group.rows, (row) =>
      formatDimensionsLabel(row.dimensions, row.dimensions_label),
    ),
    operationsLabel: uniformLabel(group.rows, getBalanceOperationsLabel),
    locationLabel: uniformLabel(group.rows, (row) => row.location_name || `#${row.location_id}`),
    qualityLabel: qualitySummary(group.rows),
  }));
}

/**
 * Строка таблицы: шапка группы (артикул с итогом) или остаток. Одиночный
 * артикул шапки не получает — раскрывать нечего, и рамка вокруг одной строки
 * шум; то же правило, что у группы из одного задания на доске (ADR-0065).
 */
type BalanceDisplayItem =
  | { kind: "group"; key: string; group: BalanceGroup; isCollapsed: boolean }
  | {
      kind: "balance";
      key: string;
      balance: StockBalanceEntry;
      isInGroup: boolean;
      isLastInGroup: boolean;
    };

function buildBalanceDisplayItems(
  groups: BalanceGroup[],
  expandedArticles: Set<string>,
): BalanceDisplayItem[] {
  const items: BalanceDisplayItem[] = [];
  for (const group of groups) {
    if (group.rows.length === 1) {
      items.push({
        kind: "balance",
        key: `balance-${group.rows[0].id}`,
        balance: group.rows[0],
        isInGroup: false,
        isLastInGroup: false,
      });
      continue;
    }
    // Группа свёрнута по умолчанию: раскрытие — осознанное действие оператора,
    // иначе список из 50 строк читается как прежде.
    const isCollapsed = !expandedArticles.has(group.key);
    items.push({ kind: "group", key: `group-${group.key}`, group, isCollapsed });
    if (isCollapsed) continue;
    group.rows.forEach((balance, index) => {
      items.push({
        kind: "balance",
        key: `balance-${balance.id}`,
        balance,
        isInGroup: true,
        isLastInGroup: index === group.rows.length - 1,
      });
    });
  }
  return items;
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

/**
 * Ячейка тела «Остатков». Отступ по вертикали — 2px: высоту строки держит
 * закреплённый `rowHeightPx` (32px), а не отступ, поэтому `py-1` здесь
 * добавлял бы к строке лишний пиксель вместе с `border-b`.
 */
const BALANCE_CELL_CLASS = "px-2 py-0.5";

const headerCellClass = `${DATA_TABLE_STYLES.headerRow} ${DATA_TABLE_STYLES.headerCell} ${TABLE_ROW_DENSE.headerCell}`;

/**
 * Строка-итог группы: артикул, сумма количеств, число строк и раскрытие.
 * Тот же словарь, что у шапки группы на доске (ADR-0065): подложка, рельс
 * слева, 1px сверху и под шапкой.
 */
function BalanceGroupRow({
  group,
  isCollapsed,
  hideLocationColumn,
  onToggle,
}: {
  group: BalanceGroup;
  isCollapsed: boolean;
  hideLocationColumn: boolean;
  onToggle: () => void;
}) {
  const cellClass = cn(BALANCE_CELL_CLASS, TABLE_ROW_STYLES.groupHeaderCell);
  return (
    <tr
      style={{ height: TABLE_ROW_DENSE.rowHeightPx }}
      aria-expanded={!isCollapsed}
      className={`cursor-pointer font-semibold ${TABLE_ROW_STYLES.defaultGroupHeader}`}
      onClick={onToggle}
    >
      <td className={cn(cellClass, TABLE_ROW_STYLES.blockRail)}>
        <div className="flex items-center gap-1">
          <button
            type="button"
            className="p-0.5 rounded text-muted-foreground transition-colors hover:bg-slate-200 hover:text-slate-800 dark:hover:bg-slate-700 dark:hover:text-slate-100"
            onClick={(event) => {
              event.stopPropagation();
              onToggle();
            }}
            title={isCollapsed ? "Раскрыть" : "Скрыть"}
          >
            {isCollapsed ? (
              <ChevronRight className="h-4 w-4 shrink-0" />
            ) : (
              <ChevronDown className="h-4 w-4 shrink-0" />
            )}
          </button>
          <span>{group.sku}</span>
          <Badge variant="secondary" className={`${TABLE_ROW_DENSE.badge} font-bold`}>
            &times;{group.rows.length}
          </Badge>
        </div>
      </td>
      {/* Итог — по строкам этой страницы: остатки одного артикула могут лежать на
          двух страницах, и «сумма по всему заводу» здесь была бы неправдой. */}
      <td className={cn(cellClass, "font-mono")} title="Сумма по строкам этой страницы">
        {fmtQty(group.totalQty)}
      </td>
      <td className={cn(cellClass, "text-xs whitespace-nowrap font-normal")}>
        {group.dimensionsLabel}
      </td>
      <td className={cn(cellClass, "max-w-[280px] text-xs font-normal text-muted-foreground")}>
        {group.operationsLabel}
      </td>
      <td className={cn(cellClass, "text-xs", qualitySummaryClass(group.rows))}>
        {group.qualityLabel}
      </td>
      {!hideLocationColumn && (
        <td className={cn(cellClass, "text-xs font-normal")}>{group.locationLabel}</td>
      )}
      <td className={cellClass} />
      <TableCornerResetCell className={TABLE_ROW_STYLES.groupHeaderCell} />
    </tr>
  );
}

/** Строка остатка: как была, плюс рёбра блока, когда она раскрыта из группы. */
function BalanceRow({
  balance,
  isInGroup,
  isLastInGroup,
  hideLocationColumn,
  onSelectProduct,
  onShowHistory,
}: {
  balance: StockBalanceEntry;
  isInGroup: boolean;
  isLastInGroup: boolean;
  hideLocationColumn: boolean;
  onSelectProduct: (productId: number) => void;
  onShowHistory: (productId: number, productSku?: string | null) => void;
}) {
  const cellClass = cn(BALANCE_CELL_CLASS, isLastInGroup && TABLE_ROW_STYLES.groupBlockBoundary);
  return (
    <tr
      // Высота закреплена, как на доске: содержимое «Операций» (RouteStepsDisplay)
      // само задаёт 24px, а строки без операций схлопывались бы до высоты текста.
      // Ровно 32px — та же плотность, что на «Заданиях» и «Передачах».
      style={{ height: TABLE_ROW_DENSE.rowHeightPx }}
      className={`border-b ${isInGroup ? TABLE_ROW_STYLES.groupBlock : "hover:bg-muted/30"}`}
    >
      <td className={cn(cellClass, isInGroup ? TABLE_ROW_STYLES.blockRail : TABLE_ROW_STYLES.emptyRail)}>
        <button
          type="button"
          className="font-medium hover:text-primary transition-colors cursor-pointer"
          onClick={() => onSelectProduct(balance.product_id)}
          title="Показать детальные остатки"
        >
          {balance.product_sku || `#${balance.product_id}`}
        </button>
      </td>
      <td className={cn(cellClass, "font-semibold font-mono")}>{fmtQty(balance.balance_qty)}</td>
      <td className={cn(cellClass, "text-xs whitespace-nowrap")}>
        {formatDimensionsLabel(balance.dimensions, balance.dimensions_label)}
      </td>
      <td className={cn(cellClass, "max-w-[280px]")}>
        {balance.completed_stages && balance.completed_stages.length > 0 ? (
          <RouteStepsDisplay steps={balance.completed_stages} compact showIcons={false} />
        ) : (
          <span className="text-xs text-muted-foreground">{getBalanceOperationsLabel(balance)}</span>
        )}
      </td>
      <td className={cellClass}>
        <span className="text-xs font-medium text-muted-foreground">
          {formatQualityStateLabel(balance.quality_state)}
        </span>
      </td>
      {!hideLocationColumn && (
        <td className={cn(cellClass, "text-xs")}>
          {balance.location_name || `#${balance.location_id}`}
        </td>
      )}
      <td className={cellClass}>
        <button
          type="button"
          className="text-xs text-muted-foreground hover:text-primary cursor-pointer"
          onClick={() => onShowHistory(balance.product_id, balance.product_sku)}
        >
          История
        </button>
      </td>
      <TableCornerResetCell
        className={isLastInGroup ? TABLE_ROW_STYLES.groupBlockBoundary : undefined}
      />
    </tr>
  );
}

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
    debouncedColumnSearchQueries,
    sortConfigs,
    handleSort: applySort,
    hasActiveFilters,
    resetAll: handleResetFilters,
  } = useFilterableTable<BalanceSortField>({
    extraHasActive: searchQuery.trim().length > 0,
    onExtraReset: onSearchQueryReset,
  });

  const columnApiParams = useMemo(
    () => buildBalanceColumnApiParams(columnFilters, debouncedColumnSearchQueries),
    [columnFilters, debouncedColumnSearchQueries],
  );

  const sort = buildBalanceSortParam(sortConfigs);
  const normalizedLocationIds = useMemo(
    () => (locationIds?.length ? [...locationIds].sort((a, b) => a - b) : undefined),
    [locationIds],
  );
  // В `resetPageDeps` уходит строка, а не массив: сравнение там по идентичности,
  // а массив приходит из мемо родителя и пересоздаётся на каждом refetch списка
  // складов — страница сбрасывалась на первую без смены фильтра (ADR-0060 п.4).
  const locationIdsKey = normalizedLocationIds?.join(",") ?? "";

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
      locationIdsKey,
      debouncedSearch,
      columnFilters,
      debouncedColumnSearchQueries,
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

  // Дерево держится на смене страницы, фильтра и сортировки, но НЕ через смену
  // склада: склад меняется выбором, и placeholder оставил бы под новым заголовком
  // остатки прежнего (ADR-0044).
  const { data, isPending } = useQuery({
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
    placeholderData: keepPreviousDataForScope<StockBalancesListResponse>(
      (key) => {
        const params = key[1] as { locationId?: number; locationIds?: number[] } | undefined;
        return `${params?.locationId ?? ""}|${params?.locationIds?.join(",") ?? ""}`;
      },
      `${locationId ?? ""}|${normalizedLocationIds?.join(",") ?? ""}`,
    ),
  });

  const balances = data?.balances ?? [];
  const balanceGroups = useMemo(() => buildBalanceGroups(balances), [balances]);
  // Раскрытые артикулы — по ключу группы: смена страницы и сортировки не
  // захлопывает то, что оператор раскрыл.
  const [expandedArticles, setExpandedArticles] = useState<Set<string>>(() => new Set());
  const displayItems = useMemo(
    () => buildBalanceDisplayItems(balanceGroups, expandedArticles),
    [balanceGroups, expandedArticles],
  );
  const toggleArticle = useCallback((key: string) => {
    setExpandedArticles((previous) => {
      const next = new Set(previous);
      if (next.has(key)) next.delete(key);
      else next.add(key);
      return next;
    });
  }, []);
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
          {isFirstRowsLoad(isPending, balances) ? (
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
                    displayItems.map((item) =>
                      item.kind === "group" ? (
                        <BalanceGroupRow
                          key={item.key}
                          group={item.group}
                          isCollapsed={item.isCollapsed}
                          hideLocationColumn={hideLocationColumn}
                          onToggle={() => toggleArticle(item.group.key)}
                        />
                      ) : (
                        <BalanceRow
                          key={item.key}
                          balance={item.balance}
                          isInGroup={item.isInGroup}
                          isLastInGroup={item.isLastInGroup}
                          hideLocationColumn={hideLocationColumn}
                          onSelectProduct={onSelectProduct}
                          onShowHistory={onShowHistory}
                        />
                      ),
                    ))}
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