import { useState, useMemo, useCallback } from "react";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { Loader2, Search, ChevronDown, ChevronRight, Upload } from "lucide-react";

import {
  getSpgList,
} from "@/shared/api/spg";
import {
  getStockBalances,
  formatQualityStateLabel,
  formatBalanceQtyInteger,
} from "@/shared/api/stock";
import type { StockBalanceEntry } from "@/shared/api/stock";
import { SpgSelector } from "../components/SpgSelector";
import { StockAdjustmentDialog } from "../components/StockAdjustmentDialog";
import { ImportRemaindersDialog } from "../components/ImportRemaindersDialog";
import { ProductStockBalanceDialog } from "../components/ProductStockBalanceDialog";
import { StockTransactionsHistoryDrawer } from "../components/StockTransactionsHistoryDrawer";
import { queryKeys } from "@/shared/api/queryKeys";
import { Input, Button, SortableFilterHeader, RouteStepsDisplay } from "@/shared/ui";
import {
  useTableQueryEngine,
  type SortConfig,
  type ColumnSortDef,
} from "@/shared/hooks/useTableQueryEngine";
import { nextMultiSortConfigs } from "@/shared/lib/multiSort";

export function SpgSnapshotPage() {
  const [selectedSpgIds, setSelectedSpgIds] = useState<number[]>([]);
  const [searchQuery, setSearchQuery] = useState("");
  const [isAdjustmentDialogOpen, setIsAdjustmentDialogOpen] = useState(false);
  const [selectedProductId, setSelectedProductId] = useState<number | null>(null);
  const [historyProductId, setHistoryProductId] = useState<number | null>(null);
  const [isImportDialogOpen, setIsImportDialogOpen] = useState(false);
  const queryClient = useQueryClient();

  const { data: spgs = [], isLoading: loadingList } = useQuery({
    queryKey: queryKeys.spg.all(),
    queryFn: getSpgList,
  });

  const { data: stockBalances = [], isLoading: loadingBalances } = useQuery({
    queryKey: queryKeys.stock.balances(),
    queryFn: () => getStockBalances(),
  });

  const handleRefresh = () => {
    void queryClient.invalidateQueries({ queryKey: queryKeys.stock.balances() });
  };

  const handleToggleSpg = (id: number) => {
    setSelectedSpgIds((prev) => {
      if (prev.includes(id)) {
        return prev.filter((x) => x !== id);
      } else {
        return [...prev, id];
      }
    });
    setSearchQuery("");
  };

  const handleClearSpg = () => {
    setSelectedSpgIds([]);
    setSearchQuery("");
  };

  const headerTitle = useMemo(() => {
    if (selectedSpgIds.length === 1) {
      const spg = spgs.find((s) => s.id === selectedSpgIds[0]);
      return spg ? spg.name : "Группа ГХП";
    }
    if (selectedSpgIds.length > 1) {
      return `Выбрано групп: ${selectedSpgIds.length}`;
    }
    return "Все группы ГХП";
  }, [spgs, selectedSpgIds]);

  const headerDescription = useMemo(() => {
    if (selectedSpgIds.length === 1) {
      const spg = spgs.find((s) => s.id === selectedSpgIds[0]);
      return spg?.description || null;
    }
    if (selectedSpgIds.length > 1) {
      return spgs
        .filter((s) => selectedSpgIds.includes(s.id))
        .map((s) => s.name)
        .join(", ");
    }
    return "Отображаются данные по всем участкам завода";
  }, [spgs, selectedSpgIds]);

  const activeSectionIds = useMemo(() => {
    const selectedSpgs = selectedSpgIds.length > 0
      ? spgs.filter((s) => selectedSpgIds.includes(s.id))
      : spgs;
    return new Set(selectedSpgs.flatMap((s) => s.sections.map((sec) => sec.section_id)));
  }, [spgs, selectedSpgIds]);

  const spgFilteredBalances = useMemo(() => {
    if (activeSectionIds.size === 0) return stockBalances;
    return stockBalances.filter((b) => activeSectionIds.has(b.location_id));
  }, [stockBalances, activeSectionIds]);

  const handleSelectProduct = (productId: number) => {
    setSelectedProductId(productId);
  };

  const handleShowHistory = (productId: number) => {
    setHistoryProductId(productId);
  };

  return (
    <div className="space-y-6 p-4">
      <div>
        <h1 className="text-2xl font-bold">Группы хранения и производства</h1>
        <p className="text-sm text-muted-foreground mt-1">
          Наличие запасов на участках
        </p>
      </div>

      {loadingList ? (
        <div className="flex items-center gap-2 text-muted-foreground">
          <Loader2 className="h-4 w-4 animate-spin" />
          Загрузка групп...
        </div>
      ) : (
        <SpgSelector
          spgs={spgs}
          selectedIds={selectedSpgIds}
          onToggle={handleToggleSpg}
          onSelect={(id) => {
            setSelectedSpgIds([id]);
            setSearchQuery("");
          }}
          onClear={handleClearSpg}
        />
      )}

      {spgs.length > 0 && (
        <div className="flex items-center justify-between border-b pb-4">
          <div>
            <h2 className="text-lg font-semibold">{headerTitle}</h2>
            {headerDescription && (
              <p className="text-sm text-muted-foreground">{headerDescription}</p>
            )}
          </div>
          <div className="flex items-center gap-2">
            <Button
              variant="outline"
              size="sm"
              onClick={() => setIsAdjustmentDialogOpen(true)}
            >
              Ручная операция
            </Button>
            <Button
              variant="outline"
              size="sm"
              onClick={() => setIsImportDialogOpen(true)}
            >
              <Upload className="h-4 w-4 mr-1" />
              Импорт из Excel
            </Button>
            <button
              type="button"
              onClick={handleRefresh}
              disabled={loadingBalances}
              className="rounded-md border border-border px-3 py-1.5 text-sm hover:bg-accent disabled:opacity-50"
            >
              {loadingBalances ? "Обновление..." : "Обновить"}
            </button>
          </div>
        </div>
      )}

      {spgs.length > 0 && (
        <div className="bg-muted/10 p-4 rounded-xl border">
          <div className="relative w-full">
            <Search className="absolute left-3 top-3 h-4 w-4 text-muted-foreground" />
            <Input
              placeholder="Глобальный поиск по артикулу или названию..."
              value={searchQuery}
              onChange={(e) => setSearchQuery(e.target.value)}
              className="w-full bg-background pl-10 h-10"
            />
          </div>
        </div>
      )}

      {spgs.length > 0 && (
        <div className="space-y-8">
          <StockBalancesPanel
            balances={spgFilteredBalances}
            isLoading={loadingBalances}
            searchQuery={searchQuery}
            onSelectProduct={handleSelectProduct}
            onShowHistory={handleShowHistory}
          />
        </div>
      )}

      <StockAdjustmentDialog
        open={isAdjustmentDialogOpen}
        onOpenChange={setIsAdjustmentDialogOpen}
      />

      <ImportRemaindersDialog
        open={isImportDialogOpen}
        onOpenChange={setIsImportDialogOpen}
        onSaved={() => {
          void queryClient.invalidateQueries({ queryKey: queryKeys.stock.balances() });
          void queryClient.invalidateQueries({ queryKey: queryKeys.stock.transactions() });
        }}
      />

      {selectedProductId !== null && (
        <ProductStockBalanceDialog
          productId={selectedProductId}
          open={selectedProductId !== null}
          onOpenChange={(open) => {
            if (!open) setSelectedProductId(null);
          }}
          onShowHistory={handleShowHistory}
        />
      )}

      <StockTransactionsHistoryDrawer
        productId={historyProductId ?? undefined}
        open={historyProductId !== null}
        onOpenChange={(open) => {
          if (!open) setHistoryProductId(null);
        }}
      />
    </div>
  );
}

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

interface StockBalancesPanelProps {
  balances: StockBalanceEntry[];
  isLoading: boolean;
  searchQuery: string;
  onSelectProduct: (productId: number) => void;
  onShowHistory: (productId: number) => void;
}

function StockBalancesPanel({ balances, isLoading, searchQuery, onSelectProduct, onShowHistory }: StockBalancesPanelProps) {
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
            Наличие на участках ({filteredCount} из {balances.length})
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
                            <RouteStepsDisplay steps={b.completed_stages} compact />
                          ) : (
                            <span className="text-xs text-muted-foreground">—</span>
                          )}
                        </td>
                        <td className="p-2">
                          <span className="text-xs font-medium text-muted-foreground">
                            {formatQualityStateLabel(b.quality_state)}
                          </span>
                        </td>
                        <td className="p-2 text-xs">
                          {b.location_name || `#${b.location_id}`}
                        </td>
                        <td className="p-2">
                          <button
                            type="button"
                            className="text-xs text-muted-foreground hover:text-primary cursor-pointer"
                            onClick={() => onShowHistory(b.product_id)}
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
