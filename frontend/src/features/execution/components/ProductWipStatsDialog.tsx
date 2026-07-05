import { useEffect, useState, useMemo } from "react";
import { Dialog, DialogContent, DialogHeader, DialogTitle, Badge, renderIcon, SortableFilterHeader, TableCornerResetCell, TableCornerResetHeader, DATA_TABLE_STYLES } from "@/shared/ui";
import { getProductWipStats, ProductWipStats, type ProductWipRemainder } from "@/shared/api/productionPlans";
import { Loader2, Layers, Package, ClipboardList, AlertCircle } from "lucide-react";
import type { SortConfig } from "@/shared/hooks/useTableQueryEngine";
import { useFilterableTable } from "@/shared/hooks/useFilterableTable";

interface ProductWipStatsDialogProps {
  sku: string | null;
  open: boolean;
  onOpenChange: (open: boolean) => void;
}

type WipRemainderSortField = "name" | "qty";

const DEFAULT_WIP_SORT: SortConfig<WipRemainderSortField>[] = [{ field: "qty", order: "desc" }];

const headerCellClass = `${DATA_TABLE_STYLES.headerRow} ${DATA_TABLE_STYLES.headerCell}`;

export function ProductWipStatsDialog({ sku, open, onOpenChange }: ProductWipStatsDialogProps) {
  const [data, setData] = useState<ProductWipStats | null>(null);
  const [isLoading, setIsLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const {
    bindColumn,
    buildFilterPredicate,
    sortConfigs,
    setSortConfigs,
    handleSort: handleSortChange,
    hasActiveColumnFilters,
    resetAll,
    resetColumnFilters,
  } = useFilterableTable<WipRemainderSortField>({
    onExtraReset: () => setSortConfigs(DEFAULT_WIP_SORT),
  });

  const sortIsNonDefault =
    sortConfigs.length !== 1 ||
    sortConfigs[0]?.field !== "qty" ||
    sortConfigs[0]?.order !== "desc";

  const hasActiveFilters = hasActiveColumnFilters || sortIsNonDefault;
  const handleResetFilters = resetAll;

  const uniqueValues = useMemo(() => {
    if (!data) return { name: [], qty: [] };
    return {
      name: Array.from(new Set(data.remainders.map((r) => r.spg_name))).sort(),
      qty: Array.from(new Set(data.remainders.map((r) => String(r.quantity)))).sort((a, b) => Number(a) - Number(b)),
    };
  }, [data]);

  const filterPredicate = useMemo(
    () => buildFilterPredicate((rem: ProductWipRemainder, field) => {
      if (field === "name") return rem.spg_name;
      return String(rem.quantity);
    }),
    [buildFilterPredicate],
  );

  const filteredRemainders = useMemo(() => {
    if (!data) return [];
    if (!filterPredicate) return data.remainders;
    return data.remainders.filter(filterPredicate);
  }, [data, filterPredicate]);

  const sortedRemainders = useMemo(() => {
    const list = [...filteredRemainders];
    if (sortConfigs.length === 0) return list;

    list.sort((a, b) => {
      for (const sort of sortConfigs) {
        let valA: any;
        let valB: any;
        
        if (sort.field === "qty") {
          valA = a.quantity;
          valB = b.quantity;
        } else if (sort.field === "name") {
          valA = a.spg_name;
          valB = b.spg_name;
        }
        
        if (valA !== valB) {
          if (typeof valA === "number" && typeof valB === "number") {
            return sort.order === "asc" ? valA - valB : valB - valA;
          }
          const strA = String(valA);
          const strB = String(valB);
          return sort.order === "asc"
            ? strA.localeCompare(strB, "ru")
            : strB.localeCompare(strA, "ru");
        }
      }
      return 0;
    });
    
    return list;
  }, [filteredRemainders, sortConfigs]);

  useEffect(() => {
    if (open) {
      setSortConfigs(DEFAULT_WIP_SORT);
    }
  }, [open, setSortConfigs]);

  useEffect(() => {
    const currentSku = sku;
    if (!open || !currentSku) {
      setData(null);
      setError(null);
      return;
    }

    setSortConfigs(DEFAULT_WIP_SORT);
    resetColumnFilters();

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
      <DialogContent className="max-w-[95vw] lg:max-w-[1400px] max-h-[90vh] overflow-y-auto flex flex-col gap-6">
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
          <div className="grid grid-cols-1 lg:grid-cols-2 gap-6 items-start">
            {/* Склады подготовки */}
            <div className="space-y-3">
              <h3 className="text-sm font-semibold flex items-center gap-2 border-b pb-2">
                <Package className="h-4 w-4 text-emerald-600" />
                <span>Остатки на складах подготовки (ГХП)</span>
              </h3>
              
              {data.remainders.length === 0 ? (
                <div className="text-xs text-muted-foreground py-2 text-center bg-muted/20 rounded-md border border-dashed">
                  Нет активных остатков на складах подготовки для данного артикула.
                </div>
              ) : (
                <div className={DATA_TABLE_STYLES.container}>
                  <table className="w-full text-xs">
                    <thead>
                      <tr>
                        <th className={`${headerCellClass} p-0`}>
                          <SortableFilterHeader
                            field="name"
                            label="ГХП (выполненные операции)"
                            currentSorts={sortConfigs}
                            onSortChange={handleSortChange}
                            values={uniqueValues.name}
                            {...bindColumn("name")}
                          />
                        </th>
                        <th className={`${headerCellClass} p-0 w-[180px] text-right`}>
                          <SortableFilterHeader
                            field="qty"
                            label="Остаток (шт.)"
                            currentSorts={sortConfigs}
                            onSortChange={handleSortChange}
                            values={uniqueValues.qty}
                            {...bindColumn("qty")}
                          />
                        </th>
                        <TableCornerResetHeader
                          hasActiveFilters={hasActiveFilters}
                          onReset={handleResetFilters}
                          dataTableHeader
                        />
                      </tr>
                    </thead>
                    <tbody>
                      {sortedRemainders.map((rem) => (
                        <tr key={`${rem.spg_id}-${rem.completed_ops}`} className="border-b last:border-0 hover:bg-muted/20">
                          <td className="px-3 py-2">
                            <div className="flex items-center gap-3">
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
                                <div className="font-medium text-xs">{rem.spg_name}</div>
                                <div className="flex flex-wrap items-center gap-1 mt-0.5">
                                  {rem.stages_with_icons && rem.stages_with_icons.length === 0 ? (
                                    <span className="text-[10px] text-muted-foreground">Без обработки</span>
                                  ) : rem.stages_with_icons ? (
                                    rem.stages_with_icons.map((s, idx) => (
                                      <span key={idx} className="flex items-center gap-1">
                                        {idx > 0 && <span className="text-muted-foreground/40 text-[10px]">›</span>}
                                        <span
                                          className="inline-flex items-center gap-1 rounded px-1.5 py-0.5 text-[11px] font-medium"
                                          style={s.op_icon_color ? {
                                            backgroundColor: s.op_icon_color + "18",
                                            color: s.op_icon_color,
                                          } : {}}
                                        >
                                          {s.op_icon && s.op_icon_color && (
                                            <span style={{ color: s.op_icon_color }}>
                                              {renderIcon(s.op_icon, "h-3 w-3")}
                                            </span>
                                          )}
                                          {s.operation_name || s.operation_code}
                                        </span>
                                      </span>
                                    ))
                                  ) : (
                                    <span className="text-[10px] text-muted-foreground">{rem.completed_ops}</span>
                                  )}
                                </div>
                              </div>
                            </div>
                          </td>
                          <td className="px-3 py-2 text-right font-mono font-semibold text-emerald-600 dark:text-emerald-400">
                            {rem.quantity.toLocaleString("ru-RU")}
                          </td>
                          <TableCornerResetCell />
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              )}
            </div>

            {/* Активные задачи на участках */}
            <div className="space-y-3">
              <h3 className="text-sm font-semibold flex items-center gap-2 border-b pb-2">
                <ClipboardList className="h-4 w-4 text-blue-600" />
                <span>В реальной работе на производственных участках</span>
              </h3>

              {data.in_work.length === 0 ? (
                <div className="text-xs text-muted-foreground py-2 text-center bg-muted/20 rounded-md border border-dashed">
                  Нет активных задач в работе (ready / in_progress) на участках.
                </div>
              ) : (
                <div className="border rounded-md overflow-hidden bg-card">
                  <table className="w-full text-xs">
                    <thead className="bg-muted/50 border-b">
                      <tr>
                        <th className="text-left px-3 py-2 font-medium text-muted-foreground">Операция (участок)</th>
                        <th className="text-center px-3 py-2 font-medium text-muted-foreground w-[80px]">Задач в работе</th>
                        <th className="text-right px-3 py-2 font-medium text-muted-foreground w-[80px]">План</th>
                        <th className="text-right px-3 py-2 font-medium text-muted-foreground w-[80px]">Выдано</th>
                        <th className="text-right px-3 py-2 font-medium text-muted-foreground w-[80px]">Завершено</th>
                      </tr>
                    </thead>
                    <tbody>
                      {data.in_work.map((task) => (
                        <tr key={`${task.section_id}-${task.operation_name}`} className="border-b last:border-0 hover:bg-muted/20">
                          <td className="px-3 py-2 flex items-center gap-3">
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
                              <div className="font-medium text-xs">{task.operation_name}</div>
                              <div className="text-[10px] text-muted-foreground">{task.section_name}</div>
                            </div>
                          </td>
                          <td className="px-3 py-2 text-center">
                            <Badge variant="secondary" className="font-mono text-xs">
                              {task.active_tasks_count}
                            </Badge>
                          </td>
                          <td className="px-3 py-2 text-right font-mono text-muted-foreground">
                            {task.planned_qty.toLocaleString("ru-RU")}
                          </td>
                          <td className="px-3 py-2 text-right font-mono font-semibold text-blue-600 dark:text-blue-400">
                            {task.issued_qty.toLocaleString("ru-RU")}
                          </td>
                          <td className="px-3 py-2 text-right font-mono text-emerald-600 dark:text-emerald-400">
                            {task.completed_qty.toLocaleString("ru-RU")}
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
