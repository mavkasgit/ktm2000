import { useEffect, useState } from "react";
import { Dialog, DialogContent, DialogHeader, DialogTitle, Badge, renderIcon } from "@/shared/ui";
import { getProductWipStats, ProductWipStats } from "@/shared/api/productionPlans";
import { Loader2, Layers, Package, ClipboardList, AlertCircle } from "lucide-react";

interface ProductWipStatsDialogProps {
  sku: string | null;
  open: boolean;
  onOpenChange: (open: boolean) => void;
}

export function ProductWipStatsDialog({ sku, open, onOpenChange }: ProductWipStatsDialogProps) {
  const [data, setData] = useState<ProductWipStats | null>(null);
  const [isLoading, setIsLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    const currentSku = sku;
    if (!open || !currentSku) {
      setData(null);
      setError(null);
      return;
    }

    let isMounted = true;
    async function loadStats() {
      setIsLoading(true);
      setError(null);
      setData(null);
      try {
        const stats = await getProductWipStats(currentSku!);
        if (isMounted) {
          setData(stats);
        }
      } catch (err: any) {
        if (isMounted) {
          setError(err?.response?.data?.detail || err?.message || "Не удалось загрузить статистику");
        }
      } finally {
        if (isMounted) {
          setIsLoading(false);
        }
      }
    }

    loadStats();

    return () => {
      isMounted = false;
    };
  }, [sku, open]);

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="sm:max-w-[760px] max-h-[85vh] overflow-y-auto flex flex-col gap-6">
        <DialogHeader>
          <DialogTitle className="flex flex-col gap-1.5 text-left">
            <div className="flex items-center gap-2 text-xl font-bold">
              <Layers className="h-5 w-5 text-primary" />
              <span>Детальная статистика</span>
              <Badge variant="outline" className="font-mono text-sm px-2.5 py-0.5 border-blue-500 text-blue-700 bg-blue-50 dark:bg-blue-950/30 dark:text-blue-400 ml-auto">
                {sku}
              </Badge>
            </div>
            {data && (
              <div className="text-sm font-normal text-muted-foreground mt-1 bg-muted/50 p-2 rounded border">
                <strong>Наименование изделия:</strong> {data.product_name}
              </div>
            )}
          </DialogTitle>
        </DialogHeader>

        {isLoading && (
          <div className="flex flex-col items-center justify-center py-12 gap-3">
            <Loader2 className="h-8 w-8 animate-spin text-primary" />
            <span className="text-sm text-muted-foreground">Загрузка статистики...</span>
          </div>
        )}

        {error && (
          <div className="flex items-center gap-3 p-4 rounded-lg bg-destructive/10 text-destructive border border-destructive/20 my-2">
            <AlertCircle className="h-5 w-5 shrink-0" />
            <div className="text-sm font-medium">{error}</div>
          </div>
        )}

        {!isLoading && !error && data && (
          <div className="flex flex-col gap-6">
            {/* Склады подготовки */}
            <div className="space-y-3">
              <h3 className="text-base font-semibold flex items-center gap-2 border-b pb-2">
                <Package className="h-4 w-4 text-emerald-600" />
                <span>Остатки на складах подготовки (ГХП)</span>
              </h3>
              
              {data.remainders.length === 0 ? (
                <div className="text-sm text-muted-foreground py-2 text-center bg-muted/20 rounded-md border border-dashed">
                  Нет активных остатков на складах подготовки для данного артикула.
                </div>
              ) : (
                <div className="border rounded-md overflow-hidden bg-card">
                  <table className="w-full text-sm">
                    <thead className="bg-muted/50 border-b">
                      <tr>
                        <th className="text-left p-3 font-medium text-muted-foreground">Код и наименование ГХП</th>
                        <th className="text-right p-3 font-medium text-muted-foreground w-[150px]">Остаток (шт.)</th>
                      </tr>
                    </thead>
                    <tbody>
                      {data.remainders.map((rem) => (
                        <tr key={rem.spg_id} className="border-b last:border-0 hover:bg-muted/20">
                          <td className="p-3 flex items-center gap-3">
                            {rem.spg_icon && rem.spg_icon_color ? (
                              <div
                                className="flex h-8 w-8 shrink-0 items-center justify-center rounded"
                                style={{ backgroundColor: rem.spg_icon_color + "20" }}
                              >
                                <span style={{ color: rem.spg_icon_color }}>
                                  {renderIcon(rem.spg_icon, "h-4 w-4")}
                                </span>
                              </div>
                            ) : (
                              <div className="flex h-8 w-8 shrink-0 items-center justify-center rounded bg-emerald-100 text-emerald-800">
                                <Package className="h-4 w-4" />
                              </div>
                            )}
                            <div>
                              <div className="font-medium">{rem.spg_code}</div>
                              <div className="text-xs text-muted-foreground">{rem.spg_name}</div>
                            </div>
                          </td>
                          <td className="p-3 text-right font-mono font-semibold text-emerald-600 dark:text-emerald-400">
                            {rem.quantity.toLocaleString("ru-RU")}
                          </td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              )}
            </div>

            {/* Активные задачи на участках */}
            <div className="space-y-3">
              <h3 className="text-base font-semibold flex items-center gap-2 border-b pb-2">
                <ClipboardList className="h-4 w-4 text-blue-600" />
                <span>В реальной работе на производственных участках</span>
              </h3>

              {data.in_work.length === 0 ? (
                <div className="text-sm text-muted-foreground py-2 text-center bg-muted/20 rounded-md border border-dashed">
                  Нет активных задач в работе (ready / in_progress) на участках.
                </div>
              ) : (
                <div className="border rounded-md overflow-hidden bg-card">
                  <table className="w-full text-sm">
                    <thead className="bg-muted/50 border-b">
                      <tr>
                        <th className="text-left p-3 font-medium text-muted-foreground">Участок</th>
                        <th className="text-center p-3 font-medium text-muted-foreground w-[100px]">Задач в работе</th>
                        <th className="text-right p-3 font-medium text-muted-foreground w-[110px]">Запланировано</th>
                        <th className="text-right p-3 font-medium text-muted-foreground w-[100px]">Сделано</th>
                        <th className="text-right p-3 font-medium text-muted-foreground w-[100px]">В работе</th>
                      </tr>
                    </thead>
                    <tbody>
                      {data.in_work.map((task) => (
                        <tr key={task.section_id} className="border-b last:border-0 hover:bg-muted/20">
                          <td className="p-3 flex items-center gap-3">
                            {task.section_icon && task.section_icon_color ? (
                              <div
                                className="flex h-8 w-8 shrink-0 items-center justify-center rounded"
                                style={{ backgroundColor: task.section_icon_color + "20" }}
                              >
                                <span style={{ color: task.section_icon_color }}>
                                  {renderIcon(task.section_icon, "h-4 w-4")}
                                </span>
                              </div>
                            ) : (
                              <div className="flex h-8 w-8 shrink-0 items-center justify-center rounded bg-blue-100 text-blue-800">
                                <ClipboardList className="h-4 w-4" />
                              </div>
                            )}
                            <div>
                              <div className="font-medium">{task.section_code}</div>
                              <div className="text-xs text-muted-foreground">{task.section_name}</div>
                            </div>
                          </td>
                          <td className="p-3 text-center">
                            <Badge variant="secondary" className="font-mono">
                              {task.active_tasks_count}
                            </Badge>
                          </td>
                          <td className="p-3 text-right font-mono text-muted-foreground">
                            {task.planned_qty.toLocaleString("ru-RU")}
                          </td>
                          <td className="p-3 text-right font-mono text-emerald-600 dark:text-emerald-400">
                            {task.completed_qty.toLocaleString("ru-RU")}
                          </td>
                          <td className="p-3 text-right font-mono font-semibold text-blue-600 dark:text-blue-400">
                            {task.in_work_qty.toLocaleString("ru-RU")}
                          </td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              )}
            </div>
          </div>
        )}
      </DialogContent>
    </Dialog>
  );
}
