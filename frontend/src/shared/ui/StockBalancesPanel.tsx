import { useState, useMemo, useCallback } from "react";
import { ChevronDown, ChevronRight } from "lucide-react";

import {
  formatQualityStateLabel,
  formatBalanceQtyInteger,
} from "@/shared/api/stock";
import type { StockBalanceEntry } from "@/shared/api/stock";
import { SortableFilterHeader } from "./SortableFilterHeader";
import { RouteStepsDisplay } from "./RouteStepsDisplay";
import {
  useTableQueryEngine,
  type SortConfig,
  type ColumnSortDef,
} from "@/shared/hooks/useTableQueryEngine";
import { nextMultiSortConfigs } from "@/shared/lib/multiSort";

type BalanceSortField = "sku" | "quantity" | "operations" | "quality" | "location";

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
      return formatBalanceQtyInteger(balance.balance_qty);
    case "operations":
      return getBalanceOperationsLabel(balance);
    case "quality":
      return formatQualityStateLabel(balance.quality_state);
    case "location":
      return balance.location_name || `#${balance.location_id}`;
  }
}

export interface StockBalancesPanelProps {
  balances: StockBalanceEntry[];
  isLoading: boolean;
  searchQuery?: string;
  onSelectProduct: (productId: number) => void;
  onShowHistory: (productId: number, productSku?: string | null) => void;
  /** Скрыть колонку «Участок» — удобно, когда остатки уже отфильтрованы по одному участку */
  hideLocationColumn?: boolean;
  title?: string;
}

export function StockBalancesPanel({
  balances,
  isLoading,
  searchQuery = "",
  onSelectProduct,
  onShowHistory,
  hideLocationColumn = false,
  title = "Наличие на участках",
}: StockBalancesPanelProps) {
  const [isExpanded, setIsExpanded] = useState(true);
  const [sortConfigs, setSortConfigs] = useState<SortConfig<BalanceSortField>[]>([]);
  const [columnFilters, setColumnFilters] = useState<Partial<Record<BalanceSortField, Set<string>>>>({});

  const handleSortChange = useCallback((field: BalanceSortField) => {
    setSortConfigs((prev) => nextMultiSortConfigs(prev, field));
  }, []);

  const handleColumnFilterChange = useCallback((field: BalanceSortField, selected: Set<string>) => {
    setColumnFilters((prev) => ({ ...prev, [field]: selected }));
  }, []);

  const searchFilteredBalances = useMemo(() => {
    if (!searchQuery.trim()) return balances;
    const q = searchQuery.toLowerCase();
    return balances.filter((b) =>
      String(b.product_id).toLowerCase().includes(q) ||
      (b.product_sku && b.product_sku.toLowerCase().includes(q)) ||
      (b.location_name && b.location_name.toLowerCase().includes(q))
    );
  }, [balances, searchQuery]);

  const sortDefs = useMemo((): ColumnSortDef<StockBalanceEntry, BalanceSortField>[] => [
    { field: "sku", getSortValue: (b) => getBalanceCellValue(b, "sku") },
    { field: "quantity", getSortValue: (b) => Number.parseFloat(String(b.balance_qty)) || 0 },
    { field: "operations", getSortValue: (b) => getBalanceOperationsLabel(b) },
    { field: "quality", getSortValue: (b) => getBalanceCellValue(b, "quality") },
    { field: "location", getSortValue: (b) => getBalanceCellValue(b, "location") },
  ], []);

  const filterPredicate = useMemo(() => {
    const hasFilters = Object.values(columnFilters).some((selected) => selected && selected.size > 0);
    if (!hasFilters) return null;
    return (balance: StockBalanceEntry) => {
      for (const [field, selected] of Object.entries(columnFilters)) {
        if (selected && selected.size > 0) {
          const cellValue = getBalanceCellValue(balance, field as BalanceSortField);
          if (!selected.has(cellValue)) return false;
        }
      }
      return true;
    };
  }, [columnFilters]);

  const uniqueValues = useMemo(() => ({
    sku: [...new Set(searchFilteredBalances.map((b) => getBalanceCellValue(b, "sku")))].sort((a, b) =>
      a.localeCompare(b, "ru"),
    ),
    quantity: [...new Set(searchFilteredBalances.map((b) => getBalanceCellValue(b, "quantity")))].sort(
      (a, b) => (Number.parseFloat(a) || 0) - (Number.parseFloat(b) || 0),
    ),
    operations: [...new Set(searchFilteredBalances.map((b) => getBalanceOperationsLabel(b)))].sort((a, b) =>
      a.localeCompare(b, "ru"),
    ),
    quality: [...new Set(searchFilteredBalances.map((b) => getBalanceCellValue(b, "quality")))].sort((a, b) =>
      a.localeCompare(b, "ru"),
    ),
    location: [...new Set(searchFilteredBalances.map((b) => getBalanceCellValue(b, "location")))].sort((a, b) =>
      a.localeCompare(b, "ru"),
    ),
  }), [searchFilteredBalances]);

  const { rows: filteredBalances, filteredCount } = useTableQueryEngine<StockBalanceEntry, BalanceSortField>({
    rows: searchFilteredBalances,
    getId: (b) => b.id,
    searchQuery: "",
    filterPredicate,
    sortConfigs,
    sortDefs,
  });

  return (
    <div className="space-y-3">
      <div className="flex items-center justify-between border-b pb-2">
        <button
          type="button"
          onClick={() => setIsExpanded(!isExpanded)}
          className="flex items-center gap-2 hover:opacity-80 transition-opacity focus:outline-none"
        >
          {isExpanded ? (
            <ChevronDown className="h-4 w-4 text-muted-foreground" />
          ) : (
            <ChevronRight className="h-4 w-4 text-muted-foreground" />
          )}
          <h3 className="text-sm font-semibold">
            {title} ({filteredCount} из {balances.length})
          </h3>
        </button>
      </div>

      {isExpanded && (
        <>
          {isLoading ? (
            <p className="text-sm text-muted-foreground py-4 text-center">Загрузка остатков...</p>
          ) : balances.length === 0 ? (
            <div className="text-center py-8 text-sm text-muted-foreground border rounded-lg border-dashed">
              Записей о наличии нет
            </div>
          ) : (
            <div className="overflow-x-auto border rounded-lg">
              {filteredBalances.length === 0 ? (
                <div className="p-8 text-center text-sm text-muted-foreground">
                  Ничего не найдено по выбранным фильтрам
                </div>
              ) : (
                <table className="w-full text-sm text-left">
                  <thead className="bg-muted/50 border-b">
                    <tr>
                      <th className="p-2 text-left font-medium">
                        <SortableFilterHeader
                          field="sku"
                          label="Артикул"
                          currentSorts={sortConfigs}
                          onSortChange={handleSortChange}
                          values={uniqueValues.sku}
                          selectedValues={columnFilters.sku ?? new Set()}
                          onFilterChange={handleColumnFilterChange}
                        />
                      </th>
                      <th className="p-2 text-left font-medium">
                        <SortableFilterHeader
                          field="quantity"
                          label="Количество"
                          currentSorts={sortConfigs}
                          onSortChange={handleSortChange}
                          values={uniqueValues.quantity}
                          selectedValues={columnFilters.quantity ?? new Set()}
                          onFilterChange={handleColumnFilterChange}
                        />
                      </th>
                      <th className="p-2 text-left font-medium min-w-[140px]">
                        <SortableFilterHeader
                          field="operations"
                          label="Операции"
                          currentSorts={sortConfigs}
                          onSortChange={handleSortChange}
                          values={uniqueValues.operations}
                          selectedValues={columnFilters.operations ?? new Set()}
                          onFilterChange={handleColumnFilterChange}
                        />
                      </th>
                      <th className="p-2 text-left font-medium">
                        <SortableFilterHeader
                          field="quality"
                          label="Статус качества"
                          currentSorts={sortConfigs}
                          onSortChange={handleSortChange}
                          values={uniqueValues.quality}
                          selectedValues={columnFilters.quality ?? new Set()}
                          onFilterChange={handleColumnFilterChange}
                        />
                      </th>
                      {!hideLocationColumn && (
                        <th className="p-2 text-left font-medium">
                          <SortableFilterHeader
                            field="location"
                            label="Участок"
                            currentSorts={sortConfigs}
                            onSortChange={handleSortChange}
                            values={uniqueValues.location}
                            selectedValues={columnFilters.location ?? new Set()}
                            onFilterChange={handleColumnFilterChange}
                          />
                        </th>
                      )}
                      <th className="p-2 text-left font-medium">Действия</th>
                    </tr>
                  </thead>
                  <tbody>
                    {filteredBalances.map((b) => (
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
                          {formatBalanceQtyInteger(b.balance_qty)}
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
                      </tr>
                    ))}
                  </tbody>
                </table>
              )}
            </div>
          )}
        </>
      )}
    </div>
  );
}