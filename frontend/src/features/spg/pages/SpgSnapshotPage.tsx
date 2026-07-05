import { useState, useMemo } from "react";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { Loader2, Search, Upload } from "lucide-react";

import {
  getSpgList,
} from "@/shared/api/spg";
import { SpgSelector } from "../components/SpgSelector";
import { StockAdjustmentDialog } from "../components/StockAdjustmentDialog";
import { ImportRemaindersDialog } from "../components/ImportRemaindersDialog";
import { ProductStockBalanceDialog } from "../components/ProductStockBalanceDialog";
import { StockTransactionsHistoryDrawer } from "../components/StockTransactionsHistoryDrawer";
import { queryKeys } from "@/shared/api/queryKeys";
import { Input, Button, StockBalancesPanel } from "@/shared/ui";

export function SpgSnapshotPage() {
  const [selectedSpgIds, setSelectedSpgIds] = useState<number[]>([]);
  const [searchQuery, setSearchQuery] = useState("");
  const [isAdjustmentDialogOpen, setIsAdjustmentDialogOpen] = useState(false);
  const [selectedProductId, setSelectedProductId] = useState<number | null>(null);
  const [historyProduct, setHistoryProduct] = useState<{
    id: number;
    sku: string | null;
  } | null>(null);
  const [isImportDialogOpen, setIsImportDialogOpen] = useState(false);
  const queryClient = useQueryClient();

  const { data: spgs = [], isLoading: loadingList } = useQuery({
    queryKey: queryKeys.spg.all(),
    queryFn: getSpgList,
  });

  const handleRefresh = () => {
    void queryClient.invalidateQueries({ queryKey: queryKeys.stock.balancesAll() });
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
    return selectedSpgs.flatMap((s) => s.sections.map((sec) => sec.section_id));
  }, [spgs, selectedSpgIds]);

  const handleSelectProduct = (productId: number) => {
    setSelectedProductId(productId);
  };

  const handleShowHistory = (productId: number, productSku?: string | null) => {
    setHistoryProduct({ id: productId, sku: productSku ?? null });
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
              className="rounded-md border border-border px-3 py-1.5 text-sm hover:bg-accent"
            >
              Обновить
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
            locationIds={activeSectionIds}
            searchQuery={searchQuery}
            onSearchQueryReset={() => setSearchQuery("")}
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
          void queryClient.invalidateQueries({ queryKey: queryKeys.stock.balancesAll() });
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
        productId={historyProduct?.id}
        productSku={historyProduct?.sku}
        open={historyProduct !== null}
        onOpenChange={(open) => {
          if (!open) setHistoryProduct(null);
        }}
      />
    </div>
  );
}