import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { Search } from "lucide-react";

import { getStockBalances } from "@/shared/api/stock";
import { queryKeys } from "@/shared/api/queryKeys";
import { Input, StockBalancesPanel } from "@/shared/ui";
import { ProductStockBalanceDialog } from "@/features/spg/components/ProductStockBalanceDialog";
import { StockTransactionsHistoryDrawer } from "@/features/spg/components/StockTransactionsHistoryDrawer";

type SectionStockBalancesProps = {
  sectionId: number;
  sectionName?: string;
};

export function SectionStockBalances({ sectionId, sectionName }: SectionStockBalancesProps) {
  const [searchQuery, setSearchQuery] = useState("");
  const [selectedProductId, setSelectedProductId] = useState<number | null>(null);
  const [historyProduct, setHistoryProduct] = useState<{
    id: number;
    sku: string | null;
  } | null>(null);

  const { data: balances = [], isLoading } = useQuery({
    queryKey: queryKeys.stock.balances(`section-${sectionId}`),
    queryFn: () => getStockBalances({ location_id: sectionId }),
    enabled: sectionId > 0,
  });

  const title = sectionName ? `Остатки на участке «${sectionName}»` : "Остатки на участке";

  return (
    <div className="space-y-3 rounded-lg border p-4">
      <div className="relative w-full">
        <Search className="absolute left-3 top-3 h-4 w-4 text-muted-foreground" />
        <Input
          placeholder="Поиск по артикулу..."
          value={searchQuery}
          onChange={(e) => setSearchQuery(e.target.value)}
          className="w-full bg-background pl-10 h-10"
        />
      </div>

      <StockBalancesPanel
        balances={balances}
        isLoading={isLoading}
        searchQuery={searchQuery}
        onSearchQueryReset={() => setSearchQuery("")}
        onSelectProduct={setSelectedProductId}
        onShowHistory={(id, sku) => setHistoryProduct({ id, sku: sku ?? null })}
        hideLocationColumn
        title={title}
      />

      {selectedProductId !== null && (
        <ProductStockBalanceDialog
          productId={selectedProductId}
          open={selectedProductId !== null}
          onOpenChange={(open) => {
            if (!open) setSelectedProductId(null);
          }}
          onShowHistory={(id, sku) => setHistoryProduct({ id, sku: sku ?? null })}
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