import { useEffect, useMemo, useState } from "react";
import { History as HistoryIcon, Loader2 } from "lucide-react";

import { Badge, Button, Dialog, DialogContent, DialogHeader, DialogTitle } from "@/shared/ui";
import {
  listSpgRemainders,
  type SpgRemainder,
  type SpgSnapshotResponse,
} from "@/shared/api/spg";
import { RemainderHistoryDrawer } from "./RemainderHistoryDrawer";

interface ProductRemaindersDialogProps {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  spgId: number;
  productId: number | null;
  snapshot: SpgSnapshotResponse | null;
  onManualOperation: (productId: number) => void;
}

export function ProductRemaindersDialog({
  open,
  onOpenChange,
  spgId,
  productId,
  snapshot,
  onManualOperation,
}: ProductRemaindersDialogProps) {
  const [remainders, setRemainders] = useState<SpgRemainder[]>([]);
  const [loading, setLoading] = useState(false);
  const [historyRemainderId, setHistoryRemainderId] = useState<number | null>(null);

  const productRow = useMemo(
    () => snapshot?.rows.find((r) => r.product_id === productId) ?? null,
    [snapshot, productId],
  );

  useEffect(() => {
    if (open && productId !== null) {
      setLoading(true);
      listSpgRemainders(spgId)
        .then((all) => setRemainders(all.filter((r) => r.product_id === productId)))
        .catch(() => setRemainders([]))
        .finally(() => setLoading(false));
    }
  }, [open, spgId, productId]);

  return (
    <>
      <Dialog open={open} onOpenChange={onOpenChange}>
        <DialogContent className="sm:max-w-[720px] max-h-[80vh] flex flex-col">
          <DialogHeader>
            <DialogTitle>
              {productRow ? `${productRow.sku} — ${productRow.product_name}` : "Остатки артикула"}
            </DialogTitle>
          </DialogHeader>

          <div className="space-y-3 overflow-auto">
            {productRow && (
              <div className="grid grid-cols-3 gap-2 text-xs">
                <div className="rounded border p-2 bg-muted/20">
                  <div className="text-muted-foreground">Доступно (SPG)</div>
                  <div className="font-semibold text-base text-purple-700">
                    {productRow.spg_available}
                  </div>
                </div>
                <div className="rounded border p-2 bg-muted/20">
                  <div className="text-muted-foreground">Выдано</div>
                  <div className="font-semibold text-base text-amber-700">
                    {productRow.issued_total}
                  </div>
                </div>
                <div className="rounded border p-2 bg-muted/20">
                  <div className="text-muted-foreground">Запланировано</div>
                  <div className="font-semibold text-base">{productRow.planned_total}</div>
                </div>
              </div>
            )}

            <div className="flex items-center justify-between">
              <h4 className="text-sm font-semibold">Остатки на участках ({remainders.length})</h4>
              {productId !== null && (
                <Button
                  size="sm"
                  variant="outline"
                  onClick={() => {
                    onManualOperation(productId);
                    onOpenChange(false);
                  }}
                >
                  Ручная операция
                </Button>
              )}
            </div>

            {loading ? (
              <div className="flex items-center gap-2 text-sm text-muted-foreground py-4 justify-center">
                <Loader2 className="h-4 w-4 animate-spin" />
                Загрузка остатков...
              </div>
            ) : remainders.length === 0 ? (
              <p className="text-sm text-muted-foreground py-4 text-center">Остатков нет</p>
            ) : (
              <div className="border rounded-lg overflow-hidden">
                <table className="w-full text-sm">
                  <thead className="bg-muted/50 border-b">
                    <tr>
                      <th className="p-2 text-left font-medium">Участок</th>
                      <th className="p-2 text-right font-medium">Кол-во</th>
                      <th className="p-2 text-right font-medium">Исходно</th>
                      <th className="p-2 text-center font-medium">Источник</th>
                      <th className="p-2 text-center font-medium">Действия</th>
                    </tr>
                  </thead>
                  <tbody>
                    {remainders.map((r) => {
                      const isNegative = r.remainder_quantity < 0;
                      return (
                        <tr key={r.id} className="border-b last:border-b-0">
                          <td className="p-2">
                            <div className="text-xs font-medium">{r.section_code}</div>
                            <div className="text-xs text-muted-foreground">{r.section_name}</div>
                          </td>
                          <td className="p-2 text-right">
                            <span className={`font-semibold ${isNegative ? "text-amber-700" : ""}`}>
                              {r.remainder_quantity}
                            </span>
                            {isNegative && (
                              <Badge variant="destructive" className="ml-2 text-[10px]">
                                в минусе
                              </Badge>
                            )}
                          </td>
                          <td className="p-2 text-right text-xs text-muted-foreground">
                            {r.original_issued}
                          </td>
                          <td className="p-2 text-center">
                            <Badge
                              variant={r.source === "manual" ? "default" : "secondary"}
                              className="text-xs"
                            >
                              {r.source === "manual" ? "Ручной" : "Задача"}
                            </Badge>
                          </td>
                          <td className="p-2 text-center">
                            <Button
                              size="sm"
                              variant="ghost"
                              onClick={() => setHistoryRemainderId(r.id)}
                              title="История"
                            >
                              <HistoryIcon className="h-3.5 w-3.5" />
                            </Button>
                          </td>
                        </tr>
                      );
                    })}
                  </tbody>
                </table>
              </div>
            )}
          </div>
        </DialogContent>
      </Dialog>

      <RemainderHistoryDrawer
        open={historyRemainderId !== null}
        onOpenChange={(o) => {
          if (!o) setHistoryRemainderId(null);
        }}
        spgId={spgId}
        remainderId={historyRemainderId}
      />
    </>
  );
}
