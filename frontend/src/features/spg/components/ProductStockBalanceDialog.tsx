import { useQuery } from "@tanstack/react-query";
import { Loader2 } from "lucide-react";

import {
  Dialog,
  DialogContent,
  DialogHeader,
  DialogTitle,
  Button,
} from "@/shared/ui";
import { getProductStockBalances } from "@/shared/api/stock";
import { getProduct } from "@/shared/api/products";
import { queryKeys } from "@/shared/api/queryKeys";

interface ProductStockBalanceDialogProps {
  productId: number;
  open: boolean;
  onOpenChange: (open: boolean) => void;
  onShowHistory?: (productId: number, productSku?: string | null) => void;
}

export function ProductStockBalanceDialog({
  productId,
  open,
  onOpenChange,
  onShowHistory,
}: ProductStockBalanceDialogProps) {
  const { data: balances = [], isLoading } = useQuery({
    queryKey: queryKeys.stock.productBalance(productId),
    queryFn: () => getProductStockBalances(productId),
    enabled: open,
  });

  const { data: product } = useQuery({
    queryKey: queryKeys.products.all(),
    queryFn: () => getProduct(productId),
    enabled: open,
  });

  const sortedBalances = [...balances].sort((a, b) =>
    (a.location_name || "").localeCompare(b.location_name || ""),
  );

  const total = sortedBalances.reduce((sum, b) => sum + parseFloat(b.balance_qty), 0);

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="sm:max-w-[600px] max-h-[90vh] overflow-y-auto">
        <DialogHeader>
          <DialogTitle>
            Остатки продукта {product ? `${product.sku} — ${product.name}` : `#${productId}`}
          </DialogTitle>
        </DialogHeader>

        <div className="space-y-4 py-2">
          {isLoading ? (
            <div className="flex items-center justify-center py-8">
              <Loader2 className="h-6 w-6 animate-spin text-muted-foreground" />
            </div>
          ) : sortedBalances.length === 0 ? (
            <div className="text-center py-8 text-sm text-muted-foreground border rounded-lg border-dashed">
              Остатков по продукту не найдено
            </div>
          ) : (
            <div className="overflow-x-auto border rounded-lg">
              <table className="w-full text-sm">
                <thead className="bg-muted/50 border-b">
                  <tr>
                    <th className="p-2 text-left font-medium">Участок</th>
                    <th className="p-2 text-left font-medium">Состояние качества</th>
                    <th className="p-2 text-right font-medium">Остаток</th>
                    <th className="p-2 text-center font-medium">Действия</th>
                  </tr>
                </thead>
                <tbody>
                  {sortedBalances.map((b) => (
                    <tr key={b.id} className="border-b hover:bg-muted/30">
                      <td className="p-2 text-xs">{b.location_name || `#${b.location_id}`}</td>
                      <td className="p-2">
                        <span className="text-xs font-medium text-muted-foreground">{b.quality_state}</span>
                      </td>
                      <td className="p-2 text-right font-semibold font-mono">{b.balance_qty}</td>
                      <td className="p-2 text-center">
                        <Button
                          size="sm"
                          variant="ghost"
                          className="h-7 text-xs"
                          onClick={() => onShowHistory?.(productId, product?.sku ?? null)}
                        >
                          История
                        </Button>
                      </td>
                    </tr>
                  ))}
                </tbody>
                <tfoot className="bg-muted/30 border-t font-semibold">
                  <tr>
                    <td colSpan={2} className="p-2 text-right">Итого:</td>
                    <td className="p-2 text-right font-mono">{String(Math.round(total))}</td>
                    <td />
                  </tr>
                </tfoot>
              </table>
            </div>
          )}
        </div>
      </DialogContent>
    </Dialog>
  );
}
