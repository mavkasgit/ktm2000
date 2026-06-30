import { useEffect, useState, useMemo } from "react";
import {
  Dialog,
  DialogContent,
  DialogHeader,
  DialogTitle,
  DialogDescription,
  DialogFooter,
  Button,
  Input,
  Badge,
} from "@/shared/ui";
import {
  getRemaindersPreview,
  type RemaindersPreviewResponse,
  type RemainderAllocationItem,
} from "@/shared/api/productionPlans";
import { Loader2, Layers, Package, ClipboardList, AlertCircle, ArrowRight } from "lucide-react";
import { fmtQty } from "./execution-utils";

interface RemainderAllocationDialogProps {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  positionId: number | null;
  positionSku: string;
  positionName: string;
  releaseQuantity: number;
  onConfirm: (allocation: RemainderAllocationItem[]) => void;
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
  const [data, setData] = useState<RemaindersPreviewResponse | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [allocations, setAllocations] = useState<Record<number, string>>({});

  useEffect(() => {
    if (!open || positionId === null) {
      setData(null);
      setError(null);
      setAllocations({});
      return;
    }

    let isMounted = true;
    async function loadPreview() {
      setLoading(true);
      setError(null);
      try {
        const preview = await getRemaindersPreview(positionId!);
        if (isMounted) {
          setData(preview);
          // Prefill allocations from default_allocation
          const initialAlloc: Record<number, string> = {};
          preview.available_remainders.forEach((rem) => {
            const defItem = preview.default_allocation.find((d) => d.remainder_id === rem.id);
            initialAlloc[rem.id] = defItem ? String(defItem.allocated_quantity) : "0";
          });
          setAllocations(initialAlloc);
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

    loadPreview();

    return () => {
      isMounted = false;
    };
  }, [open, positionId]);

  const handleResetToFifo = () => {
    if (!data) return;
    const initialAlloc: Record<number, string> = {};
    data.available_remainders.forEach((rem) => {
      const defItem = data.default_allocation.find((d) => d.remainder_id === rem.id);
      initialAlloc[rem.id] = defItem ? String(defItem.allocated_quantity) : "0";
    });
    setAllocations(initialAlloc);
  };

  const handleClearAll = () => {
    if (!data) return;
    const cleared: Record<number, string> = {};
    data.available_remainders.forEach((rem) => {
      cleared[rem.id] = "0";
    });
    setAllocations(cleared);
  };

  const stockRemainder = useMemo(() => {
    if (!data || data.available_remainders.length === 0) return null;
    return data.available_remainders.slice().sort((a, b) => a.max_completed_seq - b.max_completed_seq)[0];
  }, [data]);

  const handleFillFromStock = () => {
    if (!data || !stockRemainder) return;
    
    let otherAllocated = 0;
    Object.entries(allocations).forEach(([idStr, valStr]) => {
      const id = parseInt(idStr, 10);
      if (id !== stockRemainder.id) {
        const val = parseFloat(valStr);
        if (!isNaN(val) && val > 0) {
          otherAllocated += val;
        }
      }
    });
    
    const needed = Math.max(0, releaseQuantity - otherAllocated);
    const toAllocate = Math.min(needed, stockRemainder.remainder_quantity);
    
    setAllocations(prev => ({
      ...prev,
      [stockRemainder.id]: String(toAllocate)
    }));
  };

  // Calculations
  const sortedRemainders = useMemo(() => {
    if (!data) return [];
    return data.available_remainders.slice().sort((a, b) => {
      if (a.max_completed_seq !== b.max_completed_seq) {
        return a.max_completed_seq - b.max_completed_seq;
      }
      return a.id - b.id;
    });
  }, [data]);

  const allocationErrors = useMemo(() => {
    const errs: Record<number, string> = {};
    if (!data) return errs;

    data.available_remainders.forEach((rem) => {
      const valStr = allocations[rem.id] || "0";
      const val = parseFloat(valStr);
      if (isNaN(val) || val < 0) {
        errs[rem.id] = "Некорректное число";
      } else if (val > rem.remainder_quantity) {
        errs[rem.id] = `Макс. ${fmtQty(rem.remainder_quantity)}`;
      }
    });

    return errs;
  }, [data, allocations]);

  const totalAllocated = useMemo(() => {
    let sum = 0;
    Object.values(allocations).forEach((v) => {
      const val = parseFloat(v);
      if (!isNaN(val) && val > 0) {
        sum += val;
      }
    });
    return sum;
  }, [allocations]);

  const hasErrors = Object.keys(allocationErrors).length > 0;
  const isExceedingTotal = totalAllocated > releaseQuantity;

  const routeStepsWithPlannedQuantities = useMemo(() => {
    if (!data) return [];
    
    return data.route_steps.map((step) => {
      let covered = 0;
      data.available_remainders.forEach((rem) => {
        const qty = parseFloat(allocations[rem.id] || "0");
        if (!isNaN(qty) && qty > 0) {
          if (rem.max_completed_seq >= step.sequence) {
            covered += qty;
          }
        }
      });
      const planned = Math.max(0, releaseQuantity - covered);
      return {
        ...step,
        planned,
        covered,
      };
    });
  }, [data, allocations, releaseQuantity]);

  const handleConfirm = () => {
    if (hasErrors || isExceedingTotal) return;
    const items: RemainderAllocationItem[] = [];
    Object.entries(allocations).forEach(([idStr, valStr]) => {
      const qty = parseFloat(valStr);
      if (!isNaN(qty) && qty > 0) {
        items.push({
          remainder_id: parseInt(idStr, 10),
          quantity: qty,
        });
      }
    });
    onConfirm(items);
  };

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="max-w-[1400px] w-[95vw] h-[85vh] flex flex-col p-0 overflow-hidden gap-0">
        <DialogHeader className="p-6 pb-4 border-b shrink-0">
          <DialogTitle className="flex flex-col gap-1.5 text-left">
            <div className="flex items-center gap-2 text-xl font-bold">
              <Layers className="h-5 w-5 text-primary" />
              <span>Распределение остатков</span>
              <Badge variant="outline" className="font-mono text-sm px-2.5 py-0.5 border-blue-500 text-blue-700 bg-blue-50 dark:bg-blue-950/30 dark:text-blue-400 ml-auto">
                {positionSku}
              </Badge>
            </div>
            <div className="text-sm font-normal text-muted-foreground mt-1 bg-muted/50 p-2 rounded border">
              <strong>Артикул изделия:</strong> {positionSku} {positionName ? `(${positionName})` : ""}
            </div>
          </DialogTitle>
        </DialogHeader>

        <div className="flex-1 overflow-y-auto p-6 space-y-6">
          {loading ? (
            <div className="flex flex-col items-center justify-center py-12 gap-3">
              <Loader2 className="h-8 w-8 animate-spin text-primary" />
              <span className="text-sm text-muted-foreground">Загрузка совместимых остатков...</span>
            </div>
          ) : error ? (
            <div className="flex items-center gap-3 p-4 rounded-lg bg-destructive/10 text-destructive border border-destructive/20 my-2">
              <AlertCircle className="h-5 w-5 shrink-0" />
              <div className="text-sm font-medium">{error}</div>
            </div>
          ) : data ? (
            <div className="flex flex-col gap-6">
              <div className="grid grid-cols-1 lg:grid-cols-2 gap-6 items-start">
                {/* Склады подготовки (ГХП) */}
                <div className="space-y-3">
                  <div className="flex items-center justify-between border-b pb-2">
                    <h3 className="text-base font-semibold flex items-center gap-2">
                      <Package className="h-4 w-4 text-emerald-600" />
                      <span>Остатки на складах подготовки (ГХП)</span>
                    </h3>
                    <div className="flex items-center gap-2 text-xs">
                      <button 
                        type="button"
                        className="text-xs text-muted-foreground hover:text-foreground underline transition-colors"
                        onClick={handleResetToFifo}
                      >
                        Сбросить (FIFO)
                      </button>
                      <span className="text-muted-foreground/30">|</span>
                      <button 
                        type="button"
                        className="text-xs text-muted-foreground hover:text-foreground underline transition-colors"
                        onClick={handleClearAll}
                      >
                        Очистить всё
                      </button>
                      {stockRemainder && (
                        <>
                          <span className="text-muted-foreground/30">|</span>
                          <button 
                            type="button"
                            className="text-xs text-primary hover:text-primary/80 font-medium underline transition-colors"
                            onClick={handleFillFromStock}
                          >
                            {stockRemainder.max_completed_seq === 0 ? "Добрать со склада" : "Добрать остаток"}
                          </button>
                        </>
                      )}
                    </div>
                  </div>
                  
                  {data.available_remainders.length === 0 ? (
                    <div className="text-sm text-muted-foreground py-6 text-center bg-muted/20 rounded-md border border-dashed">
                      Нет активных остатков на складах подготовки для данного артикула.
                    </div>
                  ) : (
                    <div className="border rounded-md overflow-hidden bg-card">
                      <table className="w-full text-sm">
                        <thead className="bg-muted/50 border-b">
                          <tr>
                            <th className="text-left p-3 font-medium text-muted-foreground">ГХП (выполненные операции)</th>
                            <th className="text-right p-3 font-medium text-muted-foreground w-[260px]">Использовать / Доступно</th>
                          </tr>
                        </thead>
                        <tbody>
                          {sortedRemainders.map((rem) => {
                            const err = allocationErrors[rem.id];
                            return (
                              <tr key={rem.id} className="border-b last:border-0 hover:bg-muted/20">
                                <td className="p-3 flex items-center gap-3">
                                  <div className="flex h-8 w-8 shrink-0 items-center justify-center rounded bg-emerald-100 text-emerald-800 font-mono text-[10px] font-bold">
                                    #{rem.id}
                                  </div>
                                  <div>
                                    <div className="font-medium">{rem.spg_name}</div>
                                    <div className="text-xs text-muted-foreground">
                                      {rem.completed_stages_json
                                        .slice()
                                        .sort((a, b) => a.sequence - b.sequence)
                                        .map((s) => s.operation_name || s.operation_code)
                                        .join(", ")}{" "}
                                      (после этапа {rem.max_completed_seq})
                                    </div>
                                  </div>
                                </td>
                                <td className="p-3 text-right">
                                  <div className="flex items-center justify-end gap-3">
                                    <div className="flex flex-col items-end gap-0.5">
                                      <Input
                                        type="number"
                                        step="any"
                                        min="0"
                                        max={rem.remainder_quantity}
                                        value={allocations[rem.id] || "0"}
                                        onChange={(e) =>
                                          setAllocations((prev) => ({
                                            ...prev,
                                            [rem.id]: e.target.value,
                                          }))
                                        }
                                        onFocus={(e) => e.target.select()}
                                        className="h-8 w-24 text-right text-sm px-2 font-mono"
                                      />
                                      {err && <span className="text-[10px] text-destructive">{err}</span>}
                                    </div>
                                    <span className="font-mono font-semibold text-emerald-600 dark:text-emerald-400">
                                      / {fmtQty(rem.remainder_quantity)}
                                    </span>
                                  </div>
                                </td>
                              </tr>
                            );
                          })}
                        </tbody>
                      </table>
                    </div>
                  )}
                </div>

                {/* В реальной работе на производственных участках */}
                <div className="space-y-3">
                  <h3 className="text-base font-semibold flex items-center gap-2 border-b pb-2">
                    <ClipboardList className="h-4 w-4 text-blue-600" />
                    <span>Расчет объемов по этапам с учетом остатков</span>
                  </h3>

                  <div className="border rounded-md overflow-hidden bg-card">
                    <table className="w-full text-sm">
                      <thead className="bg-muted/50 border-b">
                        <tr>
                          <th className="text-left p-3 font-medium text-muted-foreground">Операция (участок)</th>
                          <th className="text-right p-3 font-medium text-muted-foreground w-[120px]">Исходный план</th>
                          <th className="text-center p-3 font-medium text-muted-foreground w-[60px]"></th>
                          <th className="text-right p-3 font-medium text-muted-foreground w-[160px]">План к производству</th>
                        </tr>
                      </thead>
                      <tbody>
                        {routeStepsWithPlannedQuantities.map((step) => {
                          const isFullyCovered = step.planned === 0;
                          const contributions = sortedRemainders
                            .map((rem) => {
                              const qty = parseFloat(allocations[rem.id] || "0");
                              if (!isNaN(qty) && qty > 0 && rem.max_completed_seq >= step.sequence) {
                                return {
                                  id: rem.id,
                                  qty,
                                  spg_name: rem.spg_name,
                                };
                              }
                              return null;
                            })
                            .filter(Boolean) as { id: number; qty: number; spg_name: string }[];

                          return (
                            <tr key={step.sequence} className={`border-b last:border-0 hover:bg-muted/20 ${isFullyCovered ? "bg-emerald-50/30 dark:bg-emerald-950/10" : ""}`}>
                              <td className="p-3">
                                <div className="flex items-center justify-between w-full gap-4">
                                  <div className="flex items-center gap-3">
                                    <div className="flex h-8 w-8 shrink-0 items-center justify-center rounded bg-blue-100 text-blue-800 font-mono text-xs font-bold">
                                      {step.sequence}
                                    </div>
                                    <div className="flex items-baseline gap-2">
                                      <span className="font-medium">{step.operation_name}</span>
                                      <span className="text-xs text-muted-foreground">({step.section_name})</span>
                                    </div>
                                  </div>
                                  {contributions.length > 0 && (
                                    <div className="flex flex-col items-start gap-1 text-left shrink-0 bg-emerald-50/50 dark:bg-emerald-950/20 px-2 py-0.5 rounded border border-emerald-100 dark:border-emerald-900/30">
                                      {contributions.map((c) => (
                                        <div key={c.id} className="text-[11px] flex items-center gap-1.5 text-emerald-600 dark:text-emerald-400 font-medium">
                                          <span className="inline-block w-1 h-1 rounded-full bg-emerald-500" />
                                          <span>Покрыто {fmtQty(c.qty)} шт. из #{c.id} ({c.spg_name})</span>
                                        </div>
                                      ))}
                                    </div>
                                  )}
                                </div>
                              </td>
                              <td className="p-3 text-right font-mono text-muted-foreground">
                                {fmtQty(releaseQuantity)}
                              </td>
                              <td className="p-3 text-center text-muted-foreground">
                                <ArrowRight className="h-4 w-4 inline" />
                              </td>
                              <td className="p-3 text-right font-mono font-semibold">
                                {isFullyCovered ? (
                                  <Badge variant="outline" className="border-emerald-500 text-emerald-700 bg-emerald-50 hover:bg-emerald-100 dark:bg-emerald-950/30 dark:text-emerald-400 dark:hover:bg-emerald-950/50">
                                    Из остатков ({fmtQty(step.covered || 0)})
                                  </Badge>
                                ) : (
                                  <div className="flex flex-col items-end gap-0.5">
                                    <span className={step.planned < releaseQuantity ? "text-amber-600 font-semibold" : "text-blue-600 dark:text-blue-400"}>
                                      {fmtQty(step.planned)} шт.
                                    </span>
                                    {(step.covered || 0) > 0 && (
                                      <span className="text-[10px] text-emerald-600 dark:text-emerald-400 font-medium">
                                        (покрыто {fmtQty(step.covered || 0)})
                                      </span>
                                    )}
                                  </div>
                                )}
                              </td>
                            </tr>
                          );
                        })}
                      </tbody>
                    </table>
                  </div>
                </div>
              </div>

              {/* Итоговая информация */}
              <div className="rounded-md bg-muted/50 p-4 flex items-center justify-between text-sm border border-border">
                <div className="space-y-1">
                  <div>
                    Итого из остатков: <span className="font-semibold font-mono text-emerald-600 dark:text-emerald-400">{fmtQty(totalAllocated)} шт.</span>
                  </div>
                  <div>
                    Будет произведено на 1-м этапе: <span className="font-semibold font-mono text-blue-600 dark:text-blue-400">{fmtQty(Math.max(0, releaseQuantity - totalAllocated))} шт.</span>
                  </div>
                </div>
                {isExceedingTotal && (
                  <div className="text-destructive text-xs flex items-center gap-1.5 font-medium">
                    <AlertCircle className="h-4 w-4 shrink-0" />
                    <span>Сумма распределения превышает объем запуска ({fmtQty(releaseQuantity)} шт.)</span>
                  </div>
                )}
              </div>
            </div>
          ) : null}
        </div>

        <DialogFooter className="p-6 pt-4 border-t bg-muted/20 flex gap-2 justify-end shrink-0">
          <Button variant="outline" onClick={() => onOpenChange(false)}>
            Отмена
          </Button>
          <Button
            onClick={handleConfirm}
            disabled={loading || pending || hasErrors || isExceedingTotal || !data}
            className="px-6"
          >
            {pending ? "Запуск..." : "Запустить в работу"}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
