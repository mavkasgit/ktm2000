import { useState, useMemo, useEffect } from "react";
import { useQuery, useQueries, useQueryClient } from "@tanstack/react-query";
import { Loader2, Search, ChevronDown, ChevronRight, Upload } from "lucide-react";

import {
  getSpgList,
} from "@/shared/api/spg";
import { getStockBalances } from "@/shared/api/stock";
import type { StockBalanceEntry } from "@/shared/api/stock";
import { SpgSelector } from "../components/SpgSelector";
import { DefectsListPanel } from "../components/DefectsListPanel";
import { StockAdjustmentDialog } from "../components/StockAdjustmentDialog";
import { ImportRemaindersDialog } from "../components/ImportRemaindersDialog";
import { ProductStockBalanceDialog } from "../components/ProductStockBalanceDialog";
import { StockTransactionsHistoryDrawer } from "../components/StockTransactionsHistoryDrawer";
import { getSpgDefects } from "@/shared/api/defects";
import { queryKeys } from "@/shared/api/queryKeys";
import { Input, Button, toast } from "@/shared/ui";
import { listSections } from "@/shared/api/sections";
import type { Section } from "@/shared/api/sections";

export function SpgSnapshotPage() {
  const [selectedSpgIds, setSelectedSpgIds] = useState<number[]>([]);
  const [searchQuery, setSearchQuery] = useState("");
  const [isAdjustmentDialogOpen, setIsAdjustmentDialogOpen] = useState(false);
  const [selectedProductId, setSelectedProductId] = useState<number | null>(null);
  const [historyProductId, setHistoryProductId] = useState<number | null>(null);
  const [isImportDialogOpen, setIsImportDialogOpen] = useState(false);
  const [importLocationId, setImportLocationId] = useState<number | null>(null);
  const [sections, setSections] = useState<Section[]>([]);
  const queryClient = useQueryClient();

  const { data: spgs = [], isLoading: loadingList } = useQuery({
    queryKey: queryKeys.spg.all(),
    queryFn: getSpgList,
  });

  const targetSpgIds = useMemo(() => {
    return selectedSpgIds.length > 0 ? selectedSpgIds : spgs.map((s) => s.id);
  }, [selectedSpgIds, spgs]);

  const { data: stockBalances = [], isLoading: loadingBalances } = useQuery({
    queryKey: queryKeys.stock.balances(),
    queryFn: () => getStockBalances(),
  });

  const defectsQueries = useQueries({
    queries: targetSpgIds.map((id) => ({
      queryKey: queryKeys.spg.defects(id),
      queryFn: () => getSpgDefects(id),
      enabled: spgs.length > 0,
    })),
  });

  const defects = useMemo(() => {
    return defectsQueries.flatMap((q) => q.data ?? []);
  }, [defectsQueries]);

  const loadingDefects = defectsQueries.some((q) => q.isLoading);

  const handleRefresh = () => {
    targetSpgIds.forEach((id) => {
      void queryClient.invalidateQueries({ queryKey: queryKeys.spg.defects(id) });
    });
    void queryClient.invalidateQueries({ queryKey: queryKeys.stock.balances() });
  };

  const refreshAll = handleRefresh;

  useEffect(() => {
    listSections().then(setSections).catch(() => {});
  }, []);

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

  const combinedSections = useMemo(() => {
    const selectedSpgs = selectedSpgIds.length > 0
      ? spgs.filter((s) => selectedSpgIds.includes(s.id))
      : spgs;
    return selectedSpgs.flatMap((s) => s.sections);
  }, [spgs, selectedSpgIds]);

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

  const filteredBalances = useMemo(() => {
    if (!searchQuery.trim()) return stockBalances;
    const q = searchQuery.toLowerCase();
    return stockBalances.filter((b) =>
      String(b.product_id).toLowerCase().includes(q)
    );
  }, [stockBalances, searchQuery]);

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
          Наличие запасов на участках и зарегистрированный брак
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
          onSelect={(id) => setSelectedSpgIds([id])}
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
              onClick={() => {
                const stockSection = sections.find((s) =>
                  s.type === "raw_stock" || s.type === "wip_stock" || s.type === "finished_stock",
                );
                if (stockSection) {
                  setImportLocationId(stockSection.id);
                  setIsImportDialogOpen(true);
                } else {
                  toast({
                    title: "Нет доступных складов",
                    description: "Создайте складскую секцию для импорта остатков",
                    variant: "destructive",
                  });
                }
              }}
              disabled={sections.length === 0}
            >
              <Upload className="h-4 w-4 mr-1" />
              Импорт из Excel
            </Button>
            <button
              type="button"
              onClick={handleRefresh}
              disabled={loadingBalances || loadingDefects}
              className="rounded-md border border-border px-3 py-1.5 text-sm hover:bg-accent disabled:opacity-50"
            >
              {loadingBalances || loadingDefects ? "Обновление..." : "Обновить"}
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
            balances={filteredBalances}
            isLoading={loadingBalances}
            searchQuery={searchQuery}
            onSelectProduct={handleSelectProduct}
            onShowHistory={handleShowHistory}
          />
          <DefectsListPanel
            spgId={targetSpgIds[0] ?? 0}
            spgs={spgs}
            selectedSpgIds={selectedSpgIds}
            sections={combinedSections}
            defects={defects}
            isLoading={loadingDefects}
            onRefresh={refreshAll}
            searchQuery={searchQuery}
          />
        </div>
      )}

      <StockAdjustmentDialog
        open={isAdjustmentDialogOpen}
        onOpenChange={setIsAdjustmentDialogOpen}
      />

      {importLocationId !== null && (
        <ImportRemaindersDialog
          open={isImportDialogOpen}
          onOpenChange={setIsImportDialogOpen}
          locationId={importLocationId}
          locationName={sections.find((s) => s.id === importLocationId)?.name}
          onSaved={() => {
            void queryClient.invalidateQueries({ queryKey: queryKeys.stock.balances() });
            void queryClient.invalidateQueries({ queryKey: queryKeys.stock.transactions() });
          }}
        />
      )}

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

interface StockBalancesPanelProps {
  balances: StockBalanceEntry[];
  isLoading: boolean;
  searchQuery: string;
  onSelectProduct: (productId: number) => void;
  onShowHistory: (productId: number) => void;
}

function StockBalancesPanel({ balances, isLoading, searchQuery, onSelectProduct, onShowHistory }: StockBalancesPanelProps) {
  const [isExpanded, setIsExpanded] = useState(true);

  const filteredBalances = useMemo(() => {
    if (!searchQuery.trim()) return balances;
    const q = searchQuery.toLowerCase();
    return balances.filter((b) =>
      String(b.product_id).toLowerCase().includes(q) ||
      (b.location_name && b.location_name.toLowerCase().includes(q))
    );
  }, [balances, searchQuery]);

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
            Наличие на участках ({filteredBalances.length} из {balances.length})
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
                <table className="w-full text-sm">
                  <thead className="bg-muted/50 border-b">
                    <tr>
                      <th className="p-2 text-left font-medium">Продукт</th>
                      <th className="p-2 text-left font-medium">Участок</th>
                      <th className="p-2 text-left font-medium">Статус качества</th>
                      <th className="p-2 text-right font-medium">Остаток</th>
                      <th className="p-2 text-center font-medium">Действия</th>
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
                            #{b.product_id}
                          </button>
                        </td>
                        <td className="p-2 text-xs">
                          {b.location_name || `#${b.location_id}`}
                        </td>
                        <td className="p-2">
                          <span className="text-xs font-medium text-muted-foreground">
                            {b.quality_state}
                          </span>
                        </td>
                        <td className="p-2 text-right font-semibold font-mono">
                          {b.balance_qty}
                        </td>
                        <td className="p-2 text-center">
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
