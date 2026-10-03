import { useEffect, useState, useMemo, type ReactNode } from "react";
import { Dialog, DialogContent, DialogHeader, DialogTitle, Badge, renderIcon, DataTableColumnHeader, RouteStepsDisplay, TableCornerResetCell, TableCornerResetHeader, DATA_TABLE_STYLES } from "@/shared/ui";
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
import {
  wipStatsTaskCellValue,
  wipStatsTaskColumns,
  wipStatsTaskSortValue,
  type WipStatsTaskField,
} from "../lib/wipStatsTaskColumns";

/**
 * Порядок строк по мультисортировке — тот же цикл, что у остальных
 * клиентских таблиц модалки: колонки сравниваются по порядку приоритетов,
 * числа сравниваются числами (иначе «10» встало бы раньше «4»), а строки —
 * по-русски. Пустой список сортировок оставляет порядок сервера (порядок
 * этапов маршрута), а не перемешивает строки.
 */
function sortRowsByConfigs<T, Field extends string>(
  rows: T[],
  sortConfigs: ReadonlyArray<SortConfig<Field>>,
  getSortValue: (row: T, field: Field) => string | number,
): T[] {
  if (sortConfigs.length === 0) return rows;
  return [...rows].sort((a, b) => {
    for (const sort of sortConfigs) {
      const valueA = getSortValue(a, sort.field);
      const valueB = getSortValue(b, sort.field);
      if (valueA === valueB) continue;
      if (typeof valueA === "number" && typeof valueB === "number") {
        return sort.order === "asc" ? valueA - valueB : valueB - valueA;
      }
      return sort.order === "asc"
        ? String(valueA).localeCompare(String(valueB), "ru")
        : String(valueB).localeCompare(String(valueA), "ru");
    }
    return 0;
  });
}

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

/**
 * Таблица остатков одного артикула на общих таблицах модалки.
 *
 * Парная сводка показывает такую же таблицу на каждый компонент, поэтому
 * состояние фильтров и сортировки живёт внутри компонента: у каждого
 * компонента пары своя таблица, и общий фильтр в диалоге сужал бы их все
 * одним ползунком. Одиночная сводка раньше держала это состояние в
 * компоненте диалога — отсюда были две реализации одной таблицы.
 *
 * Порядок по умолчанию — «от большего остатка»: он не считается активным
 * фильтром, и сброс возвращает его, а не пустоту.
 */
function RemaindersTable({ rows }: { rows: ProductWipRemainder[] }) {
  const {
    bindColumn,
    buildFilterPredicate,
    sortConfigs,
    handleSort,
    hasActiveFilters,
    resetAll,
  } = useFilterableTable<WipStatsField>({ defaultSort: DEFAULT_WIP_SORT });

  const uniqueValues = useMemo<Record<WipStatsField, string[]>>(
    () => ({
      name: Array.from(new Set(rows.map((row) => row.spg_name))).sort(),
      qty: Array.from(new Set(rows.map((row) => wipStatsQtyText(row)))).sort(wipStatsQtyCompare),
    }),
    [rows],
  );

  const filterPredicate = useMemo(
    () => buildFilterPredicate(wipStatsCellValue),
    [buildFilterPredicate],
  );

  const visibleRows = useMemo(() => {
    const filtered = filterPredicate ? rows.filter(filterPredicate) : rows;
    return sortRowsByConfigs(filtered, sortConfigs, wipStatsSortValue);
  }, [rows, filterPredicate, sortConfigs]);

  return (
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
                  onSortChange={handleSort}
                />
              </th>
            ))}
            <TableCornerResetHeader
              hasActiveFilters={hasActiveFilters}
              onReset={resetAll}
              dataTableHeader
            />
          </tr>
        </thead>
        <tbody>
          {visibleRows.map((rem) => (
            <RemainderRow key={remainderRowKey(rem)} rem={rem} withResetCell />
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
          {/* Ось операций — тот же RouteStepsDisplay, что на «Наличии на
              участках». Самописные чипы здесь переносились по одной на
              строку в узкой колонке модалки, и строка остатка вырастала
              вчетверо выше соседних. */}
          <div className="min-w-0">
            <div className="font-medium text-xs truncate">{rem.spg_name}</div>
            {rem.completed_stages?.length ? (
              <RouteStepsDisplay
                steps={rem.completed_stages}
                compact
                showIcons={false}
                className="mt-0.5"
              />
            ) : (
              <div className="text-[10px] text-muted-foreground mt-0.5">
                {formatCompletedOperationsLabel(rem.completed_operations, rem.completed_stages)}
              </div>
            )}
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

/** Строка блока «в работе»: порядок ячеек — из `wipStatsTaskColumns`. */
function InWorkTaskRow({ task, withResetCell = false }: { task: ProductWipTask; withResetCell?: boolean }) {
  return (
    <tr className="border-b last:border-0 hover:bg-muted/20">
      <td className="px-3 py-2">
        <div className="flex items-center gap-3">
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
          <div className="min-w-0">
            <div className="font-medium text-xs truncate">{task.operation_name}</div>
            <div className="text-[10px] text-muted-foreground truncate">{task.section_name}</div>
          </div>
        </div>
      </td>
      <td className="px-3 py-2 text-xs whitespace-nowrap text-muted-foreground">
        {formatDimensionsLabel(task.dimensions, task.dimensions_label)}
      </td>
      <td className="px-3 py-2 text-center">
        <Badge variant="secondary" className="font-mono text-xs">
          {fmtQty(task.active_tasks_count)}
        </Badge>
      </td>
      <td className="px-3 py-2 text-right font-mono text-muted-foreground">
        {fmtQty(task.planned_qty)}
      </td>
      <td className="px-3 py-2 text-right font-mono font-semibold text-blue-600 dark:text-blue-400">
        {fmtQty(task.issued_qty)}
      </td>
      <td className="px-3 py-2 text-right font-mono font-semibold text-emerald-600 dark:text-emerald-400">
        {fmtQty(task.completed_qty)}
      </td>
      {withResetCell && <TableCornerResetCell />}
    </tr>
  );
}

/**
 * Полный ключ строки блока «в работе»: участок + операция + размер.
 *
 * Один участок может нести несколько заданий одного размера (разные партии
 * плана), и без оси размера они слились бы в одну строку рендера.
 */
function inWorkRowKey(task: ProductWipTask): string {
  return `${task.section_id}-${task.operation_name}-${task.dimensions_label}`;
}

/**
 * Таблица «в работе» на общих таблицах модалки: описание колонок, поповеры
 * фильтра, сортировка и кнопка сброса — те же, что у остатков.
 *
 * Порядок по умолчанию пустой: строки приходят в порядке этапов маршрута
 * (`RouteStage.sequence`), и он осмысленнее «по убыванию остатка». Сортировка
 * появляется по клику оператора.
 */
function InWorkTable({ tasks }: { tasks: ProductWipTask[] }) {
  const {
    bindColumn,
    buildFilterPredicate,
    sortConfigs,
    handleSort,
    hasActiveFilters,
    resetAll,
  } = useFilterableTable<WipStatsTaskField>();

  const operationValues = useMemo(
    () => Array.from(new Set(tasks.map((task) => task.operation_name))).sort(),
    [tasks],
  );

  const filterPredicate = useMemo(
    () => buildFilterPredicate(wipStatsTaskCellValue),
    [buildFilterPredicate],
  );

  const visibleTasks = useMemo(() => {
    const filtered = filterPredicate ? tasks.filter(filterPredicate) : tasks;
    return sortRowsByConfigs(filtered, sortConfigs, wipStatsTaskSortValue);
  }, [tasks, filterPredicate, sortConfigs]);

  return (
    <div className={DATA_TABLE_STYLES.container}>
      <table className="w-full text-xs">
        <thead>
          <tr>
            {wipStatsTaskColumns.map((column) => (
              <th
                key={column.id}
                className={`${headerCellClass} ${column.headerClassName ?? ""}`}
                aria-sort={column.sortField ? getAriaSort(sortConfigs, column.sortField) : undefined}
              >
                <DataTableColumnHeader
                  column={column}
                  bindColumn={bindColumn}
                  values={column.filterField === "operation" ? operationValues : undefined}
                  currentSorts={sortConfigs}
                  onSortChange={handleSort}
                />
              </th>
            ))}
            <TableCornerResetHeader
              hasActiveFilters={hasActiveFilters}
              onReset={resetAll}
              dataTableHeader
            />
          </tr>
        </thead>
        <tbody>
          {visibleTasks.map((task) => (
            <InWorkTaskRow key={inWorkRowKey(task)} task={task} withResetCell />
          ))}
        </tbody>
      </table>
    </div>
  );
}

/**
 * Заголовок блока таблицы с артикулом: обе таблицы модалки стоят рядом,
 * и без подписи в каждом заголовке приходилось возвращать взглядом к
 * верхнему левому углу окна.
 */
function SectionHeading({
  icon,
  iconClassName,
  title,
  sku,
}: {
  icon: ReactNode;
  iconClassName: string;
  title: string;
  sku: string;
}) {
  return (
    <h3 className="text-sm font-semibold flex items-center gap-2 border-b pb-2">
      <span className={iconClassName}>{icon}</span>
      {/* Артикул — перед названием блока: он и есть предмет сводки, а
          название таблицы только говорит, какой разрез показан. */}
      <Badge variant="outline" className="font-mono text-xs px-2 py-0.5">
        {sku}
      </Badge>
      <span>{title}</span>
    </h3>
  );
}

function InWorkSection({ tasks, sku }: { tasks: ProductWipTask[]; sku: string }) {
  return (
    <section className="space-y-3">
      <SectionHeading
        icon={<ClipboardList className="h-4 w-4" />}
        iconClassName="text-blue-600"
        title="В реальной работе на производственных участках"
        sku={sku}
      />
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

  // Фильтры и сортировка остатков живут в самой таблице: у пары своя
  // таблица на компонент, и состояние в диалоге сужало бы их всех одним ползунком.

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
      <DialogContent className="max-w-[95vw] lg:w-[1400px] max-h-[90vh] overflow-y-auto flex flex-col gap-6">
        <DialogHeader>
          <DialogTitle className="flex flex-col gap-1.5 text-left">
            <div className="flex flex-wrap items-baseline gap-x-3 gap-y-1 text-xl font-bold">
              <Layers className="h-5 w-5 text-primary self-center" />
              <span>Детальная статистика</span>
              {/* Артикул стоит рядом с заголовком, а не прижат к правому краю:
                  `ml-auto` уводил его под кнопку закрытия. */}
              <Badge variant="outline" className="font-mono text-sm px-2.5 py-0.5 border-blue-500 text-blue-700 bg-blue-50 dark:bg-blue-950/30 dark:text-blue-400">
                {sku}
              </Badge>
              {/* Наименование — в ту же строку, сразу за артикулом: своя
                  полоса под заголовком отнимала высоту и рвала шапку надвое. */}
              {data && (
                <span className="text-base font-normal text-muted-foreground">
                  {data.product_name}
                </span>
              )}
            </div>
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
                  <SectionHeading
                    icon={<Package className="h-4 w-4" />}
                    iconClassName="text-emerald-600"
                    title="Остатки на складах подготовки (ГХП)"
                    sku={component.sku}
                  />
                  {component.product_id === null ? (
                    <EmptyNote>Артикул {component.sku} не найден в справочнике.</EmptyNote>
                  ) : component.remainders.length === 0 ? (
                    <EmptyNote>Нет активных остатков на складах подготовки для этого компонента.</EmptyNote>
                  ) : (
                    <RemaindersTable rows={component.remainders} />
                  )}
                </section>
              ))}
              <InWorkSection tasks={data.in_work} sku={data.sku} />
            </div>
          ) : (
            /* Две колонки, как было: «в работе» помещается в половину окна
               благодаря `lg:w-[1400px]` выше. С `w-auto` (дефолт Radix) окно
               брало ширину по содержимому — 900px, — и шесть колонок
               «в работе» резались по `overflow-x-hidden` молча. */
            <div className="grid grid-cols-1 lg:grid-cols-2 gap-6 items-start">
              {/* Склады подготовки */}
              <div className="space-y-3">
                <SectionHeading
                  icon={<Package className="h-4 w-4" />}
                  iconClassName="text-emerald-600"
                  title="Остатки на складах подготовки (ГХП)"
                  sku={data.sku}
                />

                {data.remainders.length === 0 ? (
                  <EmptyNote>Нет активных остатков на складах подготовки для данного артикула.</EmptyNote>
                ) : (
                  <RemaindersTable rows={data.remainders} />
                )}
              </div>

              {/* Активные задачи на участках */}
              <InWorkSection tasks={data.in_work} sku={data.sku} />
            </div>
          )
        )}
      </DialogContent>
    </Dialog>
  );
}
