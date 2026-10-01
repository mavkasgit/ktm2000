import { useEffect, useState, useMemo, type ReactNode } from "react";
import { Dialog, DialogContent, DialogHeader, DialogTitle, Badge, renderIcon, DataTableColumnHeader, TableCornerResetCell, TableCornerResetHeader, DATA_TABLE_STYLES } from "@/shared/ui";
import { getProductWipStats, ProductWipStats, type ProductWipRemainder, type ProductWipTask } from "@/shared/api/productionPlans";
import { getErrorMessage } from "@/shared/api/client";
import { formatDimensionsLabel, formatCompletedOperationsLabel } from "@/shared/api/stock";
import { errorLabels } from "@/shared/lib/generated-labels";
import { fmtQty } from "@/shared/lib/quantityFormat";
import { getAriaSort } from "@/shared/lib/multiSort";
import { Loader2, Layers, Package, ClipboardList, AlertCircle } from "lucide-react";
import type { SortConfig } from "@/shared/hooks/useTableQueryEngine";
import { useFilterableTable } from "@/shared/hooks/useFilterableTable";

import { wipStatsColumns, wipStatsCellValue, wipStatsQtyCompare, wipStatsQtyText, wipStatsSortValue, type WipStatsField } from "../lib/wipStatsColumns";

interface ProductWipStatsDialogProps {
  sku: string | null;
  open: boolean;
  onOpenChange: (open: boolean) => void;
}

const DEFAULT_WIP_SORT: SortConfig<WipStatsField>[] = [{ field: "qty", order: "desc" }];

const headerCellClass = `${DATA_TABLE_STYLES.headerRow} ${DATA_TABLE_STYLES.headerCell}`;

function EmptyNote({ children }: { children: ReactNode }) {
  return (
    <div className="text-xs text-muted-foreground py-2 text-center bg-muted/20 rounded-md border border-dashed">
      {children}
    </div>
  );
}

/** Полный ключ строки остатка: ГХП + ось операций + размер (ADR-0001, ADR-0055).
 *
 * Ключ строится по самой оси операций, а не по её подписи: подпись — текст для
 * чтения, и два разных признака с совпавшими именами операций дали бы один
 * ключ, то есть две физически разные строки остатка слились бы в рендере.
 * `null` («не зафиксировано»), `[]` («без операций») и список — разные ключи.
 */
function remainderRowKey(rem: ProductWipRemainder): string {
  const ops =
    rem.completed_operations === undefined
      ? "unknown"
      : rem.completed_operations === null
        ? "null"
        : rem.completed_operations.join("+");
  return `${rem.spg_id}-${ops}-${rem.dimensions_label}`;
}

/** Остатки одного артикула: парная сводка показывает такую таблицу на каждый компонент. */
function RemaindersTable({ rows }: { rows: ProductWipRemainder[] }) {
  return (
    <div className={DATA_TABLE_STYLES.container}>
      <table className="w-full text-xs">
        <thead>
          <tr>
            <th className={`${headerCellClass} px-3`}>ГХП (выполненные операции)</th>
            <th className={`${headerCellClass} px-2 w-[100px]`}>Размер</th>
            <th className={`${headerCellClass} px-3 w-[180px] text-right`}>Остаток (шт.)</th>
          </tr>
        </thead>
        <tbody>
          {rows.map((rem) => (
            <RemainderRow key={remainderRowKey(rem)} rem={rem} />
          ))}
        </tbody>
      </table>
    </div>
  );
}

function RemainderRow({ rem, withResetCell = false }: { rem: ProductWipRemainder; withResetCell?: boolean }) {
  return (
    <tr className="border-b last:border-0 hover:bg-muted/20">
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
              {rem.completed_stages?.length ? (
                rem.completed_stages.map((s, idx) => (
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
                <span className="text-[10px] text-muted-foreground">
                  {formatCompletedOperationsLabel(rem.completed_operations, rem.completed_stages)}
                </span>
              )}
            </div>
          </div>
        </div>
      </td>
      <td className="px-3 py-2 text-xs whitespace-nowrap text-muted-foreground">
        {formatDimensionsLabel(rem.dimensions, rem.dimensions_label)}
      </td>
      <td className="px-3 py-2 text-right font-mono font-semibold text-emerald-600 dark:text-emerald-400">
        {wipStatsQtyText(rem)}
      </td>
      {withResetCell && <TableCornerResetCell />}
    </tr>
  );
}

function InWorkTable({ tasks }: { tasks: ProductWipTask[] }) {
  return (
    <div className="border rounded-md overflow-hidden bg-card">
      <table className="w-full text-xs">
        <thead className="bg-muted/50 border-b">
          <tr>
            <th className="text-left px-3 py-2 font-medium text-muted-foreground">Операция (участок)</th>
            <th className="text-left px-3 py-2 font-medium text-muted-foreground w-[90px]">Размер</th>
            <th className="text-center px-3 py-2 font-medium text-muted-foreground w-[80px]">Задач в работе</th>
            <th className="text-right px-3 py-2 font-medium text-muted-foreground w-[80px]">План</th>
            <th className="text-right px-3 py-2 font-medium text-muted-foreground w-[80px]">Выдано</th>
            <th className="text-right px-3 py-2 font-medium text-muted-foreground w-[80px]">Завершено</th>
          </tr>
        </thead>
        <tbody>
          {tasks.map((task) => (
            <tr key={`${task.section_id}-${task.operation_name}-${task.dimensions_label}`} className="border-b last:border-0 hover:bg-muted/20">
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
              <td className="px-3 py-2 text-xs whitespace-nowrap text-muted-foreground">
                {formatDimensionsLabel(task.dimensions, task.dimensions_label)}
              </td>
              <td className="px-3 py-2 text-center">
                <Badge variant="secondary" className="font-mono text-xs">
                  {task.active_tasks_count}
                </Badge>
              </td>
              <td className="px-3 py-2 text-right font-mono text-muted-foreground">
                {fmtQty(task.planned_qty)}
              </td>
              <td className="px-3 py-2 text-right font-mono font-semibold text-blue-600 dark:text-blue-400">
                {fmtQty(task.issued_qty)}
              </td>
              <td className="px-3 py-2 text-right font-mono text-emerald-600 dark:text-emerald-400">
                {fmtQty(task.completed_qty)}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

function InWorkSection({ tasks }: { tasks: ProductWipTask[] }) {
  return (
    <section className="space-y-3">
      <h3 className="text-sm font-semibold flex items-center gap-2 border-b pb-2">
        <ClipboardList className="h-4 w-4 text-blue-600" />
        <span>В реальной работе на производственных участках</span>
      </h3>
      {tasks.length === 0 ? (
        <EmptyNote>Нет активных задач в работе (ready / in_progress) на участках.</EmptyNote>
      ) : (
        <InWorkTable tasks={tasks} />
      )}
    </section>
  );
}

function PairWarning({ code }: { code: string }) {
  return (
    <div className="flex items-center gap-3 p-3 rounded-lg bg-amber-50 text-amber-800 border border-amber-200 dark:bg-amber-950/30 dark:text-amber-300 dark:border-amber-900">
      <AlertCircle className="h-4 w-4 shrink-0" />
      {/* Код из error-канона (product_pair_not_found) — показываем как предупреждение. */}
      <div className="text-sm font-medium">{errorLabels[code] ?? code}</div>
    </div>
  );
}

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
    hasActiveFilters,
    resetAll,
    resetColumnFilters,
  } = useFilterableTable<WipStatsField>({
    // Порядок «от большего остатка» задан по умолчанию: он не считается
    // фильтром, и сброс возвращает его, а не пустоту. Условие «сортировка
    // нестандартная» раньше было написано здесь руками.
    defaultSort: DEFAULT_WIP_SORT,
  });

  const handleResetFilters = resetAll;

  const uniqueValues = useMemo<Record<WipStatsField, string[]>>(() => {
    if (!data) return { name: [], qty: [] };
    return {
      name: Array.from(new Set(data.remainders.map((r) => r.spg_name))).sort(),
      qty: Array.from(new Set(data.remainders.map((r) => wipStatsQtyText(r)))).sort(wipStatsQtyCompare),
    };
  }, [data]);

  const filterPredicate = useMemo(
    () => buildFilterPredicate(wipStatsCellValue),
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
        const fieldValue = (row: ProductWipRemainder) => wipStatsSortValue(row, sort.field);
        const valA = fieldValue(a);
        const valB = fieldValue(b);

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
      } catch (err: unknown) {
        if (isMounted) {
          setError(getErrorMessage(err) || "Не удалось загрузить статистику");
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
                <strong>{data.is_pair ? "Артикулы пары:" : "Наименование изделия:"}</strong> {data.product_name}
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
          data.is_pair ? (
            /* Пара — единый артикул плана, но сырьё хранится поштучно:
               остатки показываем отдельно по каждому компоненту. */
            <div className="space-y-6">
              {data.warning && <PairWarning code={data.warning} />}
              {data.components.map((component) => (
                <section key={component.sku} className="space-y-3">
                  <h3 className="text-sm font-semibold flex items-center gap-2 border-b pb-2">
                    <Package className="h-4 w-4 text-emerald-600" />
                    <span>Остатки на складах подготовки (ГХП)</span>
                    <Badge variant="outline" className="font-mono text-xs px-2 py-0.5">
                      {component.sku}
                    </Badge>
                  </h3>
                  {component.product_id === null ? (
                    <EmptyNote>Артикул {component.sku} не найден в справочнике.</EmptyNote>
                  ) : component.remainders.length === 0 ? (
                    <EmptyNote>Нет активных остатков на складах подготовки для этого компонента.</EmptyNote>
                  ) : (
                    <RemaindersTable rows={component.remainders} />
                  )}
                </section>
              ))}
              <InWorkSection tasks={data.in_work} />
            </div>
          ) : (
            <div className="grid grid-cols-1 lg:grid-cols-2 gap-6 items-start">
              {/* Склады подготовки */}
              <div className="space-y-3">
                <h3 className="text-sm font-semibold flex items-center gap-2 border-b pb-2">
                  <Package className="h-4 w-4 text-emerald-600" />
                  <span>Остатки на складах подготовки (ГХП)</span>
                </h3>

                {data.remainders.length === 0 ? (
                  <EmptyNote>Нет активных остатков на складах подготовки для данного артикула.</EmptyNote>
                ) : (
                  <div className={DATA_TABLE_STYLES.container}>
                    <table className="w-full text-xs">
                      <thead>
                        <tr>
                          {wipStatsColumns.map((column) => (
                            <th
                              key={column.id}
                              className={`${headerCellClass} ${column.headerClassName ?? ""}`}
                              aria-sort={column.sortField ? getAriaSort(sortConfigs, column.sortField) : undefined}
                            >
                              <DataTableColumnHeader
                                column={column}
                                bindColumn={bindColumn}
                                values={column.filterField ? uniqueValues[column.filterField] : undefined}
                                currentSorts={sortConfigs}
                                onSortChange={handleSortChange}
                              />
                            </th>
                          ))}
                          <TableCornerResetHeader
                            hasActiveFilters={hasActiveFilters}
                            onReset={handleResetFilters}
                            dataTableHeader
                          />
                        </tr>
                      </thead>
                      <tbody>
                        {sortedRemainders.map((rem) => (
                          <RemainderRow key={remainderRowKey(rem)} rem={rem} withResetCell />
                        ))}
                      </tbody>
                    </table>
                  </div>
                )}
              </div>

              {/* Активные задачи на участках */}
              <InWorkSection tasks={data.in_work} />
            </div>
          )
        )}
      </DialogContent>
    </Dialog>
  );
}
