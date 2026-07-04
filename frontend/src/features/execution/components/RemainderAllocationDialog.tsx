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
} from "@/shared/ui";
import {
  formatBalanceQtyInteger,
  formatQualityStateLabel,
  getProductStockBalances,
} from "@/shared/api/stock";
import type { StockBalanceEntry } from "@/shared/api/stock";
import { listProducts } from "@/shared/api/products";
import { fmtQty } from "@/shared/utils/fmtQty";
import {
  AlertCircle,
  AlertTriangle,
  CheckCircle2,
  Layers,
  Loader2,
  Package,
} from "lucide-react";

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

type StockReadiness = "ok" | "partial" | "empty";

const READINESS_META: Record<
  StockReadiness,
  { label: string; hint: string; Icon: typeof CheckCircle2; badge: string; panel: string }
> = {
  ok: {
    label: "Достаточно",
    hint: "Сырья хватает на плановый объём. Точное кол-во — при передаче на участок.",
    Icon: CheckCircle2,
    badge: "bg-emerald-100 text-emerald-800 border-emerald-200 dark:bg-emerald-950/40 dark:text-emerald-300",
    panel: "border-emerald-200/80 bg-emerald-50/40 dark:bg-emerald-950/20",
  },
  partial: {
    label: "Частично",
    hint: "На складе меньше плана. Запуск возможен — выдачу укажете при передаче.",
    Icon: AlertTriangle,
    badge: "bg-amber-100 text-amber-900 border-amber-200 dark:bg-amber-950/40 dark:text-amber-200",
    panel: "border-amber-200/80 bg-amber-50/40 dark:bg-amber-950/20",
  },
  empty: {
    label: "Нет на складе",
    hint: "Остатков нет. Задачи по плану создадутся — материал выдадите при передаче.",
    Icon: AlertCircle,
    badge: "bg-slate-100 text-slate-700 border-slate-200 dark:bg-slate-900 dark:text-slate-300",
    panel: "border-slate-200 bg-slate-50/60 dark:bg-slate-900/30",
  },
};

function groupBalances(balances: StockBalanceEntry[]) {
  const map = new Map<string, { location: string; quality: string; qty: number }>();
  for (const b of balances) {
    const location = b.location_name || `Участок #${b.location_id}`;
    const quality = formatQualityStateLabel(b.quality_state);
    const key = `${location}\0${quality}`;
    const prev = map.get(key);
    const add = Math.round(Number.parseFloat(b.balance_qty) || 0);
    if (prev) {
      prev.qty += add;
    } else {
      map.set(key, { location, quality, qty: add });
    }
  }
  return Array.from(map.values()).sort((a, b) => b.qty - a.qty);
}

export function RemainderAllocationDialog({
  open,
  onOpenChange,
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
  const planQty = Math.round(releaseQuantity);

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
        const products = await listProducts({ q: positionSku, limit: 1 });
        const productId = products.length > 0 ? products[0].id : 0;
        const allBalances = await getProductStockBalances(productId);
        if (isMounted) {
          setBalances(allBalances.filter((b) => b.balance_qty !== "0"));
        }
      } catch (err: unknown) {
        if (isMounted) {
          const message =
            (err as { response?: { data?: { detail?: string } }; message?: string })?.response?.data
              ?.detail ||
            (err as Error)?.message ||
            "Не удалось загрузить остатки";
          setError(message);
        }
      } finally {
        if (isMounted) setLoading(false);
      }
    }

    void loadBalances();
    return () => {
      isMounted = false;
    };
  }, [open, positionSku]);

  const totalAvailable = useMemo(
    () =>
      balances.reduce(
        (sum, b) => sum + Math.round(Number.parseFloat(b.balance_qty) || 0),
        0,
      ),
    [balances],
  );

  const readiness: StockReadiness =
    totalAvailable <= 0 ? "empty" : totalAvailable < planQty ? "partial" : "ok";

  const meta = READINESS_META[readiness];
  const reserveDelta = totalAvailable - planQty;
  const groupedBalances = useMemo(() => groupBalances(balances), [balances]);

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="max-w-md gap-0 p-0 overflow-hidden">
        <DialogHeader className="px-5 pt-5 pb-3 border-b bg-muted/30">
          <DialogTitle className="flex items-center gap-2 text-base font-semibold">
            <Layers className="h-4 w-4 text-primary shrink-0" />
            <span>Запуск в производство</span>
            <Badge
              variant="outline"
              className="ml-auto font-mono text-xs px-2 py-0 border-primary/30 text-primary"
            >
              {positionSku}
            </Badge>
          </DialogTitle>
        </DialogHeader>

        <div className="px-5 py-4 space-y-3">
          <dl className="grid grid-cols-[auto_1fr] gap-x-3 gap-y-1.5 text-sm leading-tight">
            <dt className="text-muted-foreground">Артикул</dt>
            <dd className="font-mono font-medium">{positionSku}</dd>
            {positionName ? (
              <>
                <dt className="text-muted-foreground">Наименование</dt>
                <dd className="text-foreground/90 line-clamp-2">{positionName}</dd>
              </>
            ) : null}
            <dt className="text-muted-foreground">План</dt>
            <dd className="font-mono font-semibold tabular-nums">{fmtQty(planQty)} шт.</dd>
          </dl>

          {loading ? (
            <div className="flex items-center justify-center gap-2 py-6 text-sm text-muted-foreground">
              <Loader2 className="h-4 w-4 animate-spin" />
              Проверка остатков…
            </div>
          ) : error ? (
            <div className="flex items-start gap-2 rounded-md border border-destructive/30 bg-destructive/5 px-3 py-2 text-sm text-destructive">
              <AlertCircle className="h-4 w-4 shrink-0 mt-0.5" />
              <span>{error}</span>
            </div>
          ) : (
            <section className={`rounded-lg border px-3 py-2.5 space-y-2.5 ${meta.panel}`}>
              <div className="flex items-center justify-between gap-2">
                <div className="flex items-center gap-1.5 text-xs font-medium uppercase tracking-wide text-muted-foreground">
                  <Package className="h-3.5 w-3.5" />
                  Обеспечение сырьём
                </div>
                <span
                  className={`inline-flex items-center gap-1 rounded-full border px-2 py-0.5 text-xs font-medium ${meta.badge}`}
                >
                  <meta.Icon className="h-3 w-3" />
                  {meta.label}
                </span>
              </div>

              <div className="grid grid-cols-3 divide-x rounded-md border bg-background/80 text-center text-xs">
                <div className="px-2 py-2">
                  <div className="text-muted-foreground mb-0.5">План</div>
                  <div className="font-mono font-semibold tabular-nums text-sm">{fmtQty(planQty)}</div>
                </div>
                <div className="px-2 py-2">
                  <div className="text-muted-foreground mb-0.5">Склад</div>
                  <div className="font-mono font-semibold tabular-nums text-sm">
                    {fmtQty(totalAvailable)}
                  </div>
                </div>
                <div className="px-2 py-2">
                  <div className="text-muted-foreground mb-0.5">Запас</div>
                  <div
                    className={`font-mono font-semibold tabular-nums text-sm ${
                      reserveDelta >= 0 ? "text-emerald-700 dark:text-emerald-400" : "text-amber-700 dark:text-amber-400"
                    }`}
                  >
                    {reserveDelta >= 0 ? "+" : ""}
                    {fmtQty(reserveDelta)}
                  </div>
                </div>
              </div>

              {groupedBalances.length > 0 ? (
                <table className="w-full text-xs">
                  <thead>
                    <tr className="text-muted-foreground border-b">
                      <th className="text-left font-medium py-1 pr-2">Склад</th>
                      <th className="text-right font-medium py-1 w-16">Кол-во</th>
                      <th className="text-right font-medium py-1 pl-2 w-24">Качество</th>
                    </tr>
                  </thead>
                  <tbody>
                    {groupedBalances.slice(0, 6).map((row) => (
                      <tr key={`${row.location}-${row.quality}`} className="border-b border-border/50 last:border-0">
                        <td className="py-1 pr-2 truncate max-w-[140px]" title={row.location}>
                          {row.location}
                        </td>
                        <td className="py-1 text-right font-mono tabular-nums">
                          {formatBalanceQtyInteger(row.qty)}
                        </td>
                        <td className="py-1 pl-2 text-right text-muted-foreground">{row.quality}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              ) : (
                <div className="text-xs text-muted-foreground py-1">Нет записей на складах</div>
              )}

              {groupedBalances.length > 6 && (
                <div className="text-[11px] text-muted-foreground">
                  + ещё {groupedBalances.length - 6} склад(ов)
                </div>
              )}

              <p className="text-[11px] text-muted-foreground leading-snug">{meta.hint}</p>
            </section>
          )}

          <label className="flex items-center gap-2.5 cursor-pointer select-none rounded-md border px-3 py-2.5 hover:bg-muted/40 transition-colors">
            <Checkbox
              checked={autoConsume}
              onCheckedChange={(v) => setAutoConsume(Boolean(v))}
            />
            <span className="text-sm leading-tight">
              <span className="font-medium">Автосписание со склада</span>
              <span className="block text-xs text-muted-foreground mt-0.5">
                Списать доступное при первой выдаче на участок
              </span>
            </span>
          </label>
        </div>

        <DialogFooter className="px-5 py-3 border-t bg-muted/20 gap-2">
          <Button variant="outline" size="sm" onClick={() => onOpenChange(false)}>
            Отмена
          </Button>
          <Button size="sm" onClick={() => onConfirm(autoConsume)} disabled={loading || pending}>
            {pending ? "Запуск…" : "Запустить в работу"}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}