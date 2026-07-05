import { useState } from "react";
import { Search } from "lucide-react";

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
        locationId={sectionId}
        searchQuery={searchQuery}
        onSearchQueryReset={() => setSearchQuery("")}
        onSelectProduct={setSelectedProductId}
        onShowHistory={(id, sku) => setHistoryProduct({ id, sku: sku ?? null })}
        hideLocationColumn
        title={title}
        enabled={sectionId > 0}
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