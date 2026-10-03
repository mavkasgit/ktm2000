import { useEffect, useState, useMemo } from "react";
import {
  Dialog,
  DialogContent,
  DialogHeader,
  DialogTitle,
  DialogFooter,
  Button,
  Badge,
} from "@/shared/ui";
import {
  completedOperationsCount,
  completedOperationsServerLabel,
  formatCompletedOperationsLabel,
  formatDimensionsLabel,
  formatQualityStateLabel,
  getProductStockBalances,
} from "@/shared/api/stock";
import type { StockBalanceEntry } from "@/shared/api/stock";
import { listProducts } from "@/shared/api/products";
import { fmtQty } from "@/shared/lib/quantityFormat";
import {
  AlertCircle,
  AlertTriangle,
  CheckCircle2,
  Layers,
  Loader2,
  Package,
} from "lucide-react";
/** Выбранный оператором источник: строка остатка + сколько с неё берём. */
export type SourceAllocation = { balance_id: number; quantity: number };


interface RemainderAllocationDialogProps {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  positionId: number | null;
  positionSku: string;
  positionName: string;
  releaseQuantity: number;
  onConfirm: (autoConsume: boolean, allocation: SourceAllocation[] | null) => void;
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

/**
 * Строки выдачи: одинаковые по участку, качеству, размеру и операциям остатки
 * складываются в одну строку с суммой.
 *
 * Ключ собирается по `opsKey` — серверной подписи оси операций, а не по
 * подписи ячейки: прочерк в ячейке один у `null` и `[]`, и по подписи ячейки
 * два разных остатка схлопнулись бы в одну строку выдачи (ADR-0055 п.5).
 *
 * Порядок — по убыванию числа пройденных операций (#314): подготовительный
 * склад (ближе к следующему этапу маршрута) выше сырья. При равенстве —
 * `location` → `quality` → `dims`, чтобы предвыбор не зависел от порядка
 * строк в ответе. `balanceId` — id строки `stock_balances`, он и уходит в
 * `take-to-work` как выбранный источник.
 */
export type SourceRow = {
  location: string;
  quality: string;
  dims: string;
  ops: string;
  opsKey: string;
  opsCount: number;
  qty: number;
  balanceId: number;
};

export function groupBalances(balances: StockBalanceEntry[]): SourceRow[] {
  const map = new Map<string, SourceRow>();
  for (const b of balances) {
    const location = b.location_name || `Участок #${b.location_id}`;
    const quality = formatQualityStateLabel(b.quality_state);
    // Габаритная группа (ADR-0001): разные длины одного SKU не смешиваются.
    const dims = formatDimensionsLabel(b.dimensions, b.dimensions_label);
    // ADR-0055: операции — часть идентичности остатка. Без них в ключе две
    // разные строки складывались бы в одну строку выдачи, и диалог обещал бы
    // материал, который списать нельзя: точное списание идёт по операциям.
    // Ключу нужна серверная подпись: прочерк в ячейке один у `null` и `[]`,
    // и по подписи ячейки два разных остатка схлопнулись бы в один.
    const opsKey = completedOperationsServerLabel(b.completed_operations, b.completed_stages);
    const ops = formatCompletedOperationsLabel(b.completed_operations, b.completed_stages);
    const key = `${location}\0${quality}\0${dims}\0${opsKey}`;
    const prev = map.get(key);
    const add = Math.round(Number.parseFloat(b.balance_qty) || 0);
    if (prev) {
      prev.qty += add;
    } else {
      map.set(key, {
        location,
        quality,
        dims,
        ops,
        opsKey,
        opsCount: completedOperationsCount(b.completed_operations, b.completed_stages),
        qty: add,
        balanceId: b.id,
      });
    }
  }
  return Array.from(map.values()).sort(
    (a, b) =>
      b.opsCount - a.opsCount ||
      a.location.localeCompare(b.location) ||
      a.quality.localeCompare(b.quality) ||
      a.dims.localeCompare(b.dims),
  );
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
  // Выбранный источник. null = оператор снял выбор осознанно; запустить без
  // источника можно (материал выдадут позже), молча подставлять первый
  // остаток вместо явного выбора — нельзя.
  const [selectedBalanceId, setSelectedBalanceId] = useState<number | null>(null);
  // Предвыбор — подсветка первой строки порядка, а не решение оператора
  // (#314, решение владельца): без явного выбора источника поведение прежнее,
  // материал ждёт обычной передачи. Поэтому выдача при запуске отправляется
  // только когда оператор тронул выбор, и preselect не превращается в
  // TRANSFER_SEND сам по себе.
  const [explicitChoice, setExplicitChoice] = useState(false);
  const planQty = Math.round(releaseQuantity);

  useEffect(() => {
    if (!open) {
      setBalances([]);
      setExplicitChoice(false);
      setError(null);
      return;
    }

    let isMounted = true;
    async function loadBalances() {
      setLoading(true);
      setError(null);
      try {
        const products = await listProducts({ q: positionSku, limit: 20 });
        const normalizedSku = positionSku.trim().toLowerCase();
        const product =
          products.find((p) => p.sku.trim().toLowerCase() === normalizedSku) ??
          (products.length === 1 ? products[0] : undefined);
        const productId = product?.id ?? 0;
        // `order=operations` — тот же порядок, что предвыбор на бэкенде
        // (#314): больше пройденных операций = ближе к следующему этапу.
        const allBalances = await getProductStockBalances(productId, undefined, "operations");
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


  // Предвыбор — первая строка порядка (максимум операций). Пропадает, если
  // оператор снял выбор: эффект не должен воскресить его молча.
  useEffect(() => {
    if (selectedBalanceId !== null && groupedBalances.some((r) => r.balanceId === selectedBalanceId)) {
      return;
    }
    setSelectedBalanceId(groupedBalances[0]?.balanceId ?? null);
  }, [groupedBalances, selectedBalanceId]);

  const selectedRow = useMemo(
    () => groupedBalances.find((r) => r.balanceId === selectedBalanceId) ?? null,
    [groupedBalances, selectedBalanceId],
  );

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
                <>
                  <fieldset className="space-y-1">
                    <legend className="text-[11px] font-medium uppercase tracking-wide text-muted-foreground">
                      Источник выдачи
                    </legend>
                    <table className="w-full text-xs">
                      <thead>
                        <tr className="text-muted-foreground border-b">
                          <th className="text-left font-medium py-1 pr-2 w-6" />
                          <th className="text-left font-medium py-1 pr-2">Склад</th>
                          <th className="text-right font-medium py-1 w-16">Кол-во</th>
                          <th className="text-right font-medium py-1 pl-2 w-24">Качество</th>
                        </tr>
                      </thead>
                      <tbody>
                        {groupedBalances.slice(0, 6).map((row) => {
                          const selected = row.balanceId === selectedBalanceId;
                          return (
                            <tr
                              key={`${row.location}-${row.quality}-${row.dims}-${row.opsKey}`}
                              className={`border-b border-border/50 last:border-0 cursor-pointer ${
                                selected ? "bg-primary/5" : ""
                              }`}
                              onClick={() => {
                                setSelectedBalanceId(row.balanceId);
                                setExplicitChoice(true);
                              }}
                              data-testid={`source-row-${row.balanceId}`}
                              aria-selected={selected}
                            >
                              <td className="py-1 pr-2">
                                <input
                                  type="radio"
                                  name="source-balance"
                                  className="accent-primary"
                                  checked={selected}
                                  onChange={() => {
                                    setSelectedBalanceId(row.balanceId);
                                    setExplicitChoice(true);
                                  }}
                                  aria-label={`Источник: ${row.location}, операций ${row.opsCount}`}
                                />
                              </td>
                              <td className="py-1 pr-2">
                                <div className="truncate max-w-[140px]" title={row.location}>
                                  {row.location}
                                </div>
                                <div className="text-muted-foreground truncate max-w-[140px]" title={row.ops}>
                                  {row.ops}
                                  <span className="ml-1">({row.opsCount})</span>
                                </div>
                              </td>
                              <td className="py-1 text-right font-mono tabular-nums whitespace-nowrap">
                                {fmtQty(row.qty)}
                                {row.dims !== "—" && (
                                  <span className="text-muted-foreground"> × {row.dims}</span>
                                )}
                              </td>
                              <td className="py-1 pl-2 text-right text-muted-foreground">{row.quality}</td>
                            </tr>
                          );
                        })}
                      </tbody>
                    </table>
                  </fieldset>
                  {groupedBalances.length > 6 && (
                    <div className="text-[11px] text-muted-foreground">
                      + ещё {groupedBalances.length - 6} склад(ов)
                    </div>
                  )}
                  <p className="text-[11px] text-muted-foreground leading-snug">
                    {selectedRow && explicitChoice
                      ? `Выдадим ${fmtQty(Math.min(planQty, selectedRow.qty))} шт. с «${selectedRow.location}». Операций пройдено: ${selectedRow.opsCount} — порядок источников по убыванию операций.`
                      : "Источник не выбран — материал выдадут позже, обычной передачей участку."}
                  </p>
                </>
              ) : (
                <div className="text-xs text-muted-foreground py-1">Нет записей на складах</div>
              )}

              <p className="text-[11px] text-muted-foreground leading-snug">{meta.hint}</p>
            </section>
          )}

        </div>

        <DialogFooter className="px-5 py-3 border-t bg-muted/20 gap-2">
          <Button variant="outline" size="sm" onClick={() => onOpenChange(false)}>
            Отмена
          </Button>
          <Button
            size="sm"
            onClick={() =>
              onConfirm(
                false,
                selectedRow && explicitChoice
                  ? [{ balance_id: selectedRow.balanceId, quantity: Math.min(planQty, selectedRow.qty) }]
                  : null,
              )
            }
            disabled={loading || pending}
          >
            {pending ? "Запуск…" : "Запустить в работу"}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}