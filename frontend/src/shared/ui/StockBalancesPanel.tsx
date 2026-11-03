import { useCallback, useMemo, useState } from "react";
import { useQuery } from "@tanstack/react-query";

import {
  formatQualityStateLabel,
  formatDimensionsLabel,
  formatCompletedOperationsLabel,
  formatBalanceGroupLabel,
  getStockBalances,
} from "@/shared/api/stock";
import type {
  StockBalanceEntry,
  StockBalanceItem,
  StockBalancesListResponse,
} from "@/shared/api/stock";
import { isFirstRowsLoad, keepPreviousDataForScope } from "@/shared/lib/tableQueryPlaceholder";
import { queryKeys } from "@/shared/api/queryKeys";
import { DataTableColumnHeader } from "./DataTableColumnHeader";
import { TablePanelHeader } from "./TablePanelHeader";
import { TableCornerResetCell, TableCornerResetHeader } from "./TableCornerResetHeader";
import { TablePaginationFooter } from "./TablePaginationFooter";
import { DATA_TABLE_STYLES, TABLE_ROW_DENSE } from "@/shared/lib/dataTableStyles";
import { TABLE_ROW_STYLES } from "@/shared/lib/tableRowStyles";
import { rowToneFill, type RowTone } from "@/shared/lib/rowTones";
import { cn } from "@/shared/utils/cn";
import { useFilterableTable } from "@/shared/hooks/useFilterableTable";
import { usePaginatedTableQuery } from "@/shared/hooks/usePaginatedTableQuery";
import { buildColumnApiParams, buildColumnFilterValues } from "@/shared/lib/columnSpecs";
import { getAriaSort } from "@/shared/lib/multiSort";
import { RouteStepsDisplay } from "./RouteStepsDisplay";

import { buildBalanceSortParam, DEFAULT_BALANCE_SORT, type BalanceSortField } from "@/shared/lib/stockSortParams";
import { stockBalanceColumns } from "@/shared/lib/stockBalanceColumns";
import { useDebouncedValue } from "@/shared/lib/useDebouncedValue";
import { fmtQty } from "@/shared/lib/quantityFormat";
import { Badge } from "./badge";
import { ChevronDown, ChevronRight } from "lucide-react";

/**
 * Строки одной кучи. Сервер уже сгруппировал эквивалентные артикулы по осям
 * `(участок, качество, размер, операции)` и отдал раскрытие в `items[]`;
 * клиент не строит групп и не складывает количества — иначе сумма «одной
 * кучи» разошлась бы с пагинацией и сортировкой, которые считает сервер.
 *
 * `items` нет только у ответа SKU-уровня (`by-product`): там куча — одна
 * строка, и панель показывает её так же, как одиночную группу.
 */
function balanceItems(balance: StockBalanceEntry): StockBalanceItem[] {
  if (balance.items?.length) return balance.items;
  return [
    {
      balance_id: balance.id,
      product_id: balance.product_id,
      sku: balance.product_sku,
      quantity: balance.balance_qty,
    },
  ];
}

/**
 * Ключ раскрытия группы — `id` строки, то есть минимальный `balance_id` кучи:
 * сервер отдаёт его стабильно, и смена страницы/сортировки не захлопывает
 * то, что оператор раскрыл.
 */
function balanceGroupKey(balance: StockBalanceEntry): string {
  return String(balance.id);
}

/**
 * Строка таблицы: шапка группы (несколько SKU в одной куче) или фактическая
 * SKU-строка. Одиночная куча шапки не получает — раскрывать нечего, и рамка
 * вокруг одной строки шум (то же правило, что у группы из одного задания на
 * доске, ADR-0065).
 */
type BalanceDisplayItem =
  | { kind: "group"; key: string; group: StockBalanceEntry; isCollapsed: boolean }
  | {
      kind: "item";
      key: string;
      group: StockBalanceEntry;
      item: StockBalanceItem;
      isInGroup: boolean;
      isLastInGroup: boolean;
    };

function buildBalanceDisplayItems(
  balances: StockBalanceEntry[],
  expandedGroups: Set<string>,
): BalanceDisplayItem[] {
  const items: BalanceDisplayItem[] = [];
  for (const balance of balances) {
    const groupItems = balanceItems(balance);
    if (groupItems.length <= 1) {
      items.push({
        kind: "item",
        key: `balance-${groupItems[0].balance_id}`,
        group: balance,
        item: groupItems[0],
        isInGroup: false,
        isLastInGroup: false,
      });
      continue;
    }
    // Группа свёрнута по умолчанию: раскрытие — осознанное действие оператора,
    // иначе список из 50 строк читается как прежде.
    const groupKey = balanceGroupKey(balance);
    const isCollapsed = !expandedGroups.has(groupKey);
    items.push({ kind: "group", key: `group-${groupKey}`, group: balance, isCollapsed });
    if (isCollapsed) continue;
    groupItems.forEach((item, index) => {
      items.push({
        kind: "item",
        key: `balance-${item.balance_id}`,
        group: balance,
        item,
        isInGroup: true,
        isLastInGroup: index === groupItems.length - 1,
      });
    });
  }
  return items;
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
  /**
   * `?sort=` при отсутствии ручной сортировки. По умолчанию — `sku:asc`
   * (дефолт эндпоинта); вкладка участка передаёт `quantity:desc`.
   */
  defaultSort?: string;
}

/**
 * Ячейка тела «Остатков». Отступ по вертикали — 2px: высоту строки держит
 * закреплённый `rowHeightPx` (32px), а не отступ, поэтому `py-1` здесь
 * добавлял бы к строке лишний пиксель вместе с `border-b`.
 */
const BALANCE_CELL_CLASS = "px-2 py-0.5";

const headerCellClass = `${DATA_TABLE_STYLES.headerRow} ${DATA_TABLE_STYLES.headerCell} ${TABLE_ROW_DENSE.headerCell}`;

/**
 * Тон строки остатка — по качеству, из общего словаря (`shared/lib/rowTones`):
 * брак красный, переделка янтарная, годное — без тона. Рельс блока в остатках
 * остаётся нейтральным (ADR-0065): он значит «это один блок», и цвет там не
 * начал бы значить вторую вещь.
 */
function balanceRowTone(qualityState: string): RowTone {
  const state = qualityState.toUpperCase();
  if (state === "SCRAP" || state === "FINAL_SCRAP") return "scrap";
  if (state === "REWORK") return "activeRunning";
  return "plain";
}

/** Подсветка статуса качества: брак обязан читаться цветом, а не только словом. */
function balanceQualityClass(qualityState: string): string {
  const state = qualityState.toUpperCase();
  if (state === "SCRAP" || state === "FINAL_SCRAP") {
    return "text-red-600 dark:text-red-400 font-medium";
  }
  if (state === "REWORK") {
    return "text-amber-700 dark:text-amber-400 font-medium";
  }
  return "text-muted-foreground";
}

/**
 * Операции строки — те же, что в её пилюлях (`RouteStepsDisplay`): имена
 * операций этапов, а без этапов — подпись строки (прочерк для обоих пустых
 * состояний). Все SKU одной кучи делят эту ось, поэтому значение одно.
 */
function BalanceOperationsCell({ balance }: { balance: StockBalanceEntry }) {
  if (balance.completed_stages && balance.completed_stages.length > 0) {
    return <RouteStepsDisplay steps={balance.completed_stages} compact showIcons={false} />;
  }
  return (
    <span className="text-xs text-muted-foreground">
      {formatCompletedOperationsLabel(balance.completed_operations, balance.completed_stages)}
    </span>
  );
}

/**
 * Строка-итог группы эквивалентов: подпись «A, B (эквиваленты)», сумма кучи,
 * число SKU и раскрытие. Тот же словарь, что у шапки группы на доске
 * (ADR-0065): подложка, рельс слева, 1px сверху и под шапкой.
 */
function BalanceGroupRow({
  group,
  isCollapsed,
  hideLocationColumn,
  onToggle,
}: {
  group: StockBalanceEntry;
  isCollapsed: boolean;
  hideLocationColumn: boolean;
  onToggle: () => void;
}) {
  const cellClass = cn(BALANCE_CELL_CLASS, TABLE_ROW_STYLES.groupHeaderCell);
  const itemsCount = balanceItems(group).length;
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
          <span>{formatBalanceGroupLabel(group)}</span>
          <Badge variant="secondary" className={`${TABLE_ROW_DENSE.badge} font-bold`}>
            &times;{itemsCount}
          </Badge>
        </div>
      </td>
      {/* Сумма — серверная: группа уже не разрезана страницей, и складывать
          клиенту нечего. */}
      <td className={cn(cellClass, "font-mono")} title="Сумма по группе эквивалентов">
        {fmtQty(group.balance_qty)}
      </td>
      <td className={cn(cellClass, "max-w-[120px] text-xs font-normal")}>
        <span className="block truncate">
          {formatDimensionsLabel(group.dimensions, group.dimensions_label)}
        </span>
      </td>
      <td className={cn(cellClass, "max-w-[280px] text-xs font-normal text-muted-foreground")}>
        <span className="block truncate">
          {formatCompletedOperationsLabel(group.completed_operations, group.completed_stages)}
        </span>
      </td>
      <td className={cn(cellClass, "max-w-[220px] text-xs", balanceQualityClass(group.quality_state))}>
        <span className="block truncate">{formatQualityStateLabel(group.quality_state)}</span>
      </td>
      {!hideLocationColumn && (
        <td className={cn(cellClass, "max-w-[160px] text-xs font-normal")}>
          <span className="block truncate">
            {group.location_name || `#${group.location_id}`}
          </span>
        </td>
      )}
      <td className={cellClass} />
      <TableCornerResetCell className={TABLE_ROW_STYLES.groupHeaderCell} />
    </tr>
  );
}

/**
 * Фактическая SKU-строка: одиночная куча или ребёнок раскрытой группы.
 * Участок, качество, размер и операции берутся у группы — это её оси, все
 * строки кучи их делят; «История» — по `product_id` самой строки.
 */
function BalanceItemRow({
  group,
  item,
  isInGroup,
  isLastInGroup,
  hideLocationColumn,
  onSelectProduct,
  onShowHistory,
}: {
  group: StockBalanceEntry;
  item: StockBalanceItem;
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
      className={`border-b ${isInGroup ? TABLE_ROW_STYLES.groupBlock : rowToneFill(balanceRowTone(group.quality_state))}`}
    >
      <td className={cn(cellClass, isInGroup ? TABLE_ROW_STYLES.blockRail : TABLE_ROW_STYLES.emptyRail)}>
        <button
          type="button"
          className="font-medium hover:text-primary transition-colors cursor-pointer"
          onClick={() => onSelectProduct(item.product_id)}
          title="Показать детальные остатки"
        >
          {item.sku || `#${item.product_id}`}
        </button>
      </td>
      <td className={cn(cellClass, "font-semibold font-mono")}>{fmtQty(item.quantity)}</td>
      <td className={cn(cellClass, "text-xs whitespace-nowrap")}>
        {formatDimensionsLabel(group.dimensions, group.dimensions_label)}
      </td>
      <td className={cn(cellClass, "max-w-[280px]")}>
        <BalanceOperationsCell balance={group} />
      </td>
      <td className={cellClass}>
        <span className="text-xs font-medium text-muted-foreground">
          {formatQualityStateLabel(group.quality_state)}
        </span>
      </td>
      {!hideLocationColumn && (
        <td className={cn(cellClass, "text-xs")}>
          {group.location_name || `#${group.location_id}`}
        </td>
      )}
      <td className={cellClass}>
        <button
          type="button"
          className="text-xs text-muted-foreground hover:text-primary cursor-pointer"
          onClick={() => onShowHistory(item.product_id, item.sku)}
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
  defaultSort = DEFAULT_BALANCE_SORT,
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

  const sort = buildBalanceSortParam(sortConfigs, defaultSort);
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

  // Порядок строк — серверный: сортировка и пагинация считаются по группам,
  // и клиентская перестановка развела бы порядок с `total` и страницами.
  const balances = data?.balances ?? [];
  // Раскрытые группы — по ключу строки: смена страницы и сортировки не
  // захлопывает то, что оператор раскрыл.
  const [expandedGroups, setExpandedGroups] = useState<Set<string>>(() => new Set());
  const displayItems = useMemo(
    () => buildBalanceDisplayItems(balances, expandedGroups),
    [balances, expandedGroups],
  );
  const toggleGroup = useCallback((key: string) => {
    setExpandedGroups((previous) => {
      const next = new Set(previous);
      if (next.has(key)) next.delete(key);
      else next.add(key);
      return next;
    });
  }, []);
  const total = data?.total ?? 0;
  const totalPages = getTotalPages(total);

  // Список значений попапера — из описания колонок: читатель значения объявлен
  // в самой колонке (`cellValue`/`filterValuesFrom`), поэтому список и фильтр
  // берут одно значение (#322).
  const uniqueValues: Partial<Record<BalanceSortField, string[]>> = useMemo(
    () => buildColumnFilterValues(balances, stockBalanceColumns),
    [balances],
  );

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
                          onToggle={() => toggleGroup(balanceGroupKey(item.group))}
                        />
                      ) : (
                        <BalanceItemRow
                          key={item.key}
                          group={item.group}
                          item={item.item}
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
