import { useEffect, useState, useMemo } from "react";
import {
  Dialog,
  DialogContent,
  DialogHeader,
  DialogTitle,
  DialogFooter,
  Button,
  Badge,
  Checkbox,
  renderIcon,
} from "@/shared/ui";
import { getProductStockBalances } from "@/shared/api/stock";
import type { StockBalanceEntry } from "@/shared/api/stock";
import { listProducts } from "@/shared/api/products";
import { Loader2, Layers, Package, AlertCircle, AlertTriangle } from "lucide-react";

interface RemainderAllocationDialogProps {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  positionId: number | null;
  positionSku: string;
  positionName: string;
  releaseQuantity: number;
  onConfirm: (autoConsume: boolean) => void;
  pending: boolean;
}

export function RemainderAllocationDialog({
  open,
  onOpenChange,
  positionId,
  positionSku,
  positionName,
  releaseQuantity,
  onConfirm,
  pending,
}: RemainderAllocationDialogProps) {
  const [balances, setBalances] = useState<StockBalanceEntry[]>([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [autoConsume, setAutoConsume] = useState(false);

  useEffect(() => {
    if (!open) {
      setBalances([]);
      setError(null);
      setAutoConsume(false);
      return;
    }

    let isMounted = true;
    async function loadBalances() {
      setLoading(true);
      setError(null);
      try {
        // Lookup product by SKU to get product_id for balance query
        const products = await listProducts({ q: positionSku, limit: 1 });
        const productId = products.length > 0 ? products[0].id : 0;
        const allBalances = await getProductStockBalances(productId);
        if (isMounted) {
          setBalances(allBalances.filter((b) => b.balance_qty !== "0"));
        }
      } catch (err: any) {
        if (isMounted) {
          setError(err?.response?.data?.detail || err?.message || "Не удалось загрузить данные остатков");
        }
      } finally {
        if (isMounted) {
          setLoading(false);
        }
      }
    }

    loadBalances();
    return () => {
      isMounted = false;
    };
  }, [open, positionSku]);

  const totalAvailable = useMemo(() => {
    return balances.reduce((sum, b) => sum + parseFloat(b.balance_qty), 0);
  }, [balances]);

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="max-w-[600px]">
        <DialogHeader>
          <DialogTitle className="flex flex-col gap-1.5 text-left">
            <div className="flex items-center gap-2 text-xl font-bold">
              <Layers className="h-5 w-5 text-primary" />
              <span>Запуск в производство</span>
              <Badge variant="outline" className="font-mono text-sm px-2.5 py-0.5 border-blue-500 text-blue-700 bg-blue-50 dark:bg-blue-950/30 dark:text-blue-400 ml-auto">
                {positionSku}
              </Badge>
            </div>
            <div className="text-sm font-normal text-muted-foreground mt-1 bg-muted/50 p-2 rounded border">
              <strong>Артикул:</strong> {positionSku} {positionName ? `(${positionName})` : ""}
              {" · "}
              <strong>План:</strong> {releaseQuantity} шт.
            </div>
          </DialogTitle>
        </DialogHeader>

        <div className="space-y-4 py-2">
          {loading ? (
            <div className="flex flex-col items-center justify-center py-8 gap-3">
              <Loader2 className="h-8 w-8 animate-spin text-primary" />
              <span className="text-sm text-muted-foreground">Загрузка остатков...</span>
            </div>
          ) : error ? (
            <div className="flex items-center gap-3 p-4 rounded-lg bg-destructive/10 text-destructive border border-destructive/20">
              <AlertCircle className="h-5 w-5 shrink-0" />
              <div className="text-sm font-medium">{error}</div>
            </div>
          ) : (
            <>
              <div className="rounded-md border bg-muted/20 p-3">
                <div className="flex items-center gap-2 text-sm">
                  <Package className="h-4 w-4 text-emerald-600" />
                  <span className="font-medium">Доступно на складах:</span>
                  <span className="font-mono font-bold">{String(Math.round(totalAvailable))} шт.</span>
                </div>
                {balances.length > 0 && (
                  <div className="mt-2 text-xs text-muted-foreground">
                    {balances.slice(0, 5).map((b) => (
                      <div key={b.id} className="flex justify-between py-0.5">
                        <span>{b.location_name || `#${b.location_id}`}</span>
                        <span className="font-mono">{b.balance_qty} шт. ({b.quality_state})</span>
                      </div>
                    ))}
                    {balances.length > 5 && (
                      <div className="text-muted-foreground pt-1">+ ещё {balances.length - 5} записей</div>
                    )}
                  </div>
                )}
              </div>

              {totalAvailable < releaseQuantity && (
                <div className="flex items-start gap-3 p-3 rounded-md border border-amber-300 bg-amber-50 text-amber-900 dark:bg-amber-950/30 dark:text-amber-200">
                  <AlertTriangle className="h-5 w-5 shrink-0 text-amber-600 dark:text-amber-400 mt-0.5" />
                  <div className="text-sm">
                    <div className="font-medium">
                      {totalAvailable === 0 ? "Нет доступных остатков" : "Недостаточно остатков"}
                    </div>
                    <div className="text-xs mt-0.5 text-amber-800 dark:text-amber-300">
                      {totalAvailable === 0
                        ? "На складах нет материалов для списания. Брать в работу нечего."
                        : `Доступно ${String(Math.round(totalAvailable))} из ${releaseQuantity} шт. по плану. Возможен только частичный запуск.`}
                    </div>
                  </div>
                </div>
              )}

              <label className="flex items-start gap-2 cursor-pointer select-none rounded-md border border-slate-200 bg-slate-50/50 p-3 hover:bg-slate-50">
                <Checkbox
                  checked={autoConsume}
                  onCheckedChange={(v) => setAutoConsume(Boolean(v))}
                  className="mt-0.5"
                />
                <div className="flex-1">
                  <div className="text-sm font-medium">Автоматически потребить со склада</div>
                  <div className="text-xs text-muted-foreground mt-0.5">
                    Списать доступные остатки в производство. Если отключено — потребуется
                    ручное распределение материалов.
                  </div>
                </div>
              </label>
            </>
          )}
        </div>

        <DialogFooter className="flex gap-2 justify-end">
          <Button variant="outline" onClick={() => onOpenChange(false)}>
            Отмена
          </Button>
          <Button
            onClick={() => onConfirm(autoConsume)}
            disabled={loading || pending || totalAvailable === 0}
            className="px-6"
          >
            {pending ? "Запуск..." : "Запустить в работу"}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
