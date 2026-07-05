import { useMemo, useRef } from "react";
import { ListChecks } from "lucide-react";
import { ProductionPlanningRow } from "@/shared/api/productionPlans";
import {
  Button,
  FiltersPanel,
  VirtualizedTableBody,
  SortableFilterHeader,
  TableCornerResetHeader,
  TablePaginationFooter,
  DATA_TABLE_STYLES,
  type FiltersPanelField,
} from "@/shared/ui";
import type { PageLimitOption } from "@/shared/hooks/usePaginatedTableQuery";
import type { useFilterableTable } from "@/shared/hooks/useFilterableTable";
import { SortConfig } from "@/shared/hooks/useTableQueryEngine";
import { ExecutionSortField, positionStatusLabels } from "./execution-utils";
import { fmtQty } from "@/shared/utils/fmtQty";
import { ExecutionRow } from "./ExecutionRow";
import { getExecutionTableColumns } from "./execution-table-columns";
import {
  type BulkActionDefinition,
  type BulkActionResultItem,
  type BulkActionSummary,
  type BulkRunnerProgress,
} from "@/shared/bulk";

interface ExecutionTableProps {
  rows: ProductionPlanningRow[];
  isLoading: boolean;
  bulkMode: boolean;
  totalRows: number;
  releasedRows: number;
  completedRows: number;
  // filters
  filterFields: FiltersPanelField[];
  activeFilterSummary: { count: number; labels: string[] };
  tableHasActiveFilters: boolean;
  // sorting
  sortConfigs: SortConfig<ExecutionSortField>[];
  handleSortChange: (field: ExecutionSortField) => void;
  getAriaSort: (field: ExecutionSortField) => "none" | "ascending" | "descending";
  bindColumn: ReturnType<typeof useFilterableTable<ExecutionSortField>>["bindColumn"];
  uniqueValuesByField: {
    id: string[];
    row: string[];
    plan: string[];
    sku: string[];
    name: string[];
    qty: string[];
    route: string[];
    status: string[];
    stage: string[];
  };
  hideColumnIds: boolean;
  // bulk
  bulkSelection: {
    selectedIds: Set<number>;
    selectedCount: number;
    selectOne: (id: number, checked?: boolean) => void;
    selectAllFiltered: (ids: Iterable<number>) => void;
    clear: () => void;
    pruneTo: (ids: Iterable<number>) => void;
    isSelected: (id: number) => boolean;
    isAllSelected: (ids: Iterable<number>) => boolean;
    isIndeterminate: (ids: Iterable<number>) => boolean;
  };
  bulkProgress: BulkRunnerProgress | null;
  bulkSummary: BulkActionSummary | null;
  selectedBulkActionId: string;
  onActionChange: (id: string) => void;
  executionBulkActions: BulkActionDefinition<number, Map<number, ProductionPlanningRow>>[];
  onRunSelectedBulkAction: (actionId?: string) => void;
  onEnterBulkMode: () => void;
  onExitBulkMode: () => void;
  // lookups
  sectionMetaById: Map<number, { icon: string | null; icon_color: string | null }>;
  rowById: Map<number, ProductionPlanningRow>;
  // row actions
  onOpenDetail: (id: number) => void;
  onSingleLaunch: (row: ProductionPlanningRow) => void;
  onManualPass: (row: ProductionPlanningRow) => void;
  onCancel: (row: ProductionPlanningRow) => void;
  onRestore: (row: ProductionPlanningRow) => void;
  onSoftDelete: (row: ProductionPlanningRow) => void;
  onToggleSelect: (id: number) => void;
  onSelectAll: () => void;
  onResetAll: () => void;
  onRequestBulkSoftDelete: () => void;
  onRemoveSelection?: (id: number) => void;
  onSkuClick: (sku: string) => void;
  tableScrollRef: React.MutableRefObject<HTMLDivElement | null>;
  page: number;
  totalPages: number;
  total: number;
  limit: PageLimitOption;
  onPageChange: (page: number) => void;
  onLimitChange: (limit: PageLimitOption) => void;
  rangeLabel: string;
}

export function ExecutionTable({
  rows,
  isLoading,
  bulkMode,
  totalRows,
  releasedRows,
  completedRows,
  filterFields,
  activeFilterSummary,
  tableHasActiveFilters,
  sortConfigs,
  handleSortChange,
  getAriaSort,
  bindColumn,
  uniqueValuesByField,
  hideColumnIds,
  bulkSelection,
  bulkProgress,
  bulkSummary,
  selectedBulkActionId,
  onActionChange,
  executionBulkActions,
  onRunSelectedBulkAction,
  onEnterBulkMode,
  onExitBulkMode,
  sectionMetaById,
  rowById,
  onOpenDetail,
  onSingleLaunch,
  onManualPass,
  onCancel,
  onRestore,
  onSoftDelete,
  onToggleSelect,
  onSelectAll,
  onResetAll,
  onRequestBulkSoftDelete,
  onRemoveSelection,
  onSkuClick,
  tableScrollRef,
  page,
  totalPages,
  total,
  limit,
  onPageChange,
  onLimitChange,
  rangeLabel,
}: ExecutionTableProps) {
  const visibleColumns = getExecutionTableColumns(hideColumnIds);
  const headerCellClass = `${DATA_TABLE_STYLES.headerRow} ${DATA_TABLE_STYLES.headerCell}`;

  const actionVariant = (actionId: string): "default" | "destructive" | "outline" | "success" => {
    switch (actionId) {
      case "take-to-work": return "outline";
      case "restore": return "success";
      case "cancel": case "soft-delete": return "destructive";
      default: return "default";
    }
  };

  const eligibleBulkActions = useMemo(
    () =>
      executionBulkActions
        .map((action) => {
          let count = 0;
          for (const id of bulkSelection.selectedIds) {
            if (action.isEligible?.(id, rowById)) count++;
          }
          return { action, eligibleCount: count };
        })
        .filter(({ eligibleCount }) => eligibleCount > 0),
    [executionBulkActions, bulkSelection.selectedIds, rowById],
  );

  const cancelActionLabel = useMemo(() => {
    let hasApproved = false;
    let hasReleased = false;
    for (const id of bulkSelection.selectedIds) {
      const row = rowById.get(id);
      if (row) {
        if (row.position_status === "approved") hasApproved = true;
        if (row.position_status === "released") hasReleased = true;
      }
    }
    if (hasApproved && hasReleased) return "Отменить / Остановить";
    if (hasReleased) return "Остановить";
    return "Отменить";
  }, [bulkSelection.selectedIds, rowById]);

  const bulkActions = useMemo(() => {
    const running = Boolean(bulkProgress?.running);

    if (bulkSelection.selectedCount === 0) {
      return (
        <div className="flex items-center gap-2">
          <span className="text-sm text-muted-foreground">Нет выбранных строк</span>
        </div>
      );
    }

    return (
      <div className="flex items-center gap-2 flex-wrap">
        <span className="text-sm font-medium whitespace-nowrap">Выбрано: {bulkSelection.selectedCount}</span>
        {eligibleBulkActions.map(({ action, eligibleCount }) => {
          const variant = actionVariant(action.id);
          const label = action.id === "cancel" ? cancelActionLabel : action.label;
          return (
            <Button
              key={action.id}
              size="sm"
              variant={variant}
              className="h-8 text-xs"
              onClick={() => {
                onRunSelectedBulkAction(action.id);
              }}
              disabled={running}
            >
              {running && bulkProgress
                ? `${label} (${bulkProgress.completed}/${bulkProgress.total})`
                : label}
              {!running && eligibleCount < bulkSelection.selectedCount && (
                <span className="ml-1 opacity-60">({eligibleCount})</span>
              )}
            </Button>
          );
        })}
      </div>
    );
  }, [bulkSelection.selectedCount, bulkSelection.selectedIds, bulkProgress, eligibleBulkActions, onRunSelectedBulkAction, cancelActionLabel]);

  return (
    <>
      <header className="page-header">
        <div>
          <h1 className="page-title">Контроль выполнения</h1>
          <div className="flex flex-wrap gap-3 text-sm">
            <span className="px-3 py-1 rounded-full bg-muted">Строк всего: {totalRows}</span>
            <span className="px-3 py-1 rounded-full bg-emerald-100 text-emerald-700">В работе: {releasedRows}</span>
            <span className="px-3 py-1 rounded-full bg-violet-100 text-violet-700">Завершено: {completedRows}</span>
          </div>
        </div>
      </header>

      <div className="min-w-0">
        {bulkMode && (
          <div className="mb-3">
            <div className="flex items-center justify-between">
              <div className="flex items-center gap-2">
                <ListChecks className="h-5 w-5 text-primary" />
                <span className="text-lg font-semibold">Групповые операции</span>
                <span className="text-sm text-muted-foreground">Выбрано: {bulkSelection.selectedCount}</span>
              </div>
              <Button variant="outline" size="sm" onClick={onExitBulkMode}>
                Выйти
              </Button>
            </div>
            <p className="text-sm text-muted-foreground mt-1">
              Выбирайте позиции кликом по строке, <kbd className="px-1 py-0.5 text-xs rounded bg-muted font-mono">Shift+Click</kbd> — диапазон. Примените действие через кнопки выше. <kbd className="px-1 py-0.5 text-xs rounded bg-muted font-mono">Esc</kbd> — выход.
            </p>
          </div>
        )}

        <section className="min-w-0 space-y-3">
          <FiltersPanel
            compact
            fields={filterFields}
            activeSummary={activeFilterSummary}
            actions={bulkActions}
            onSelectAll={() => {
              onEnterBulkMode();
              onSelectAll();
            }}
            totalRowCount={total}
          />

          <div
            ref={tableScrollRef}
            className={`max-w-full ${DATA_TABLE_STYLES.container}`}
            style={{ maxHeight: '70vh' }}
          >
            <div style={{ maxWidth: 1850 }}>
            <table className="execution-table w-full table-fixed border-separate border-spacing-0">
              <colgroup>
                {visibleColumns.map((column) => (
                  <col
                    key={column.id}
                    className={column.colClassName}
                    style={{ width: column.width }}
                  />
                ))}
                <col style={{ width: "2.5rem" }} />
              </colgroup>
              <thead>
                <tr>
                  {visibleColumns.map((column) => (
                    <th
                      key={column.id}
                      className={`${headerCellClass} ${column.headerClassName ?? ""}`}
                      aria-sort={column.sortField ? getAriaSort(column.sortField) : undefined}
                    >
                      {column.sortField ? (
                        <SortableFilterHeader
                          field={column.sortField}
                          label={column.label}
                          currentSorts={sortConfigs}
                          onSortChange={handleSortChange}
                          values={uniqueValuesByField[column.sortField]}
                          {...bindColumn(column.sortField)}
                          valueLabel={column.sortField === "status" ? (v) => positionStatusLabels[v] ?? v : undefined}
                        />
                      ) : column.id === "actions" ? (
                        <span className="block truncate">{column.label}</span>
                      ) : (
                        <span className="block truncate">{column.label}</span>
                      )}
                    </th>
                  ))}
                  <TableCornerResetHeader
                    hasActiveFilters={tableHasActiveFilters}
                    onReset={onResetAll}
                    dataTableHeader
                  />
                </tr>
              </thead>
              <VirtualizedTableBody
                rows={rows}
                rowHeight={48}
                colSpan={visibleColumns.length + 1}
                scrollContainerRef={tableScrollRef as React.RefObject<HTMLElement | null>}
                renderRow={(row, rowIdx) => (
                  <ExecutionRow
                    key={row.plan_position_id}
                    row={row}
                    bulkMode={bulkMode}
                    isSelected={bulkSelection.isSelected(row.plan_position_id)}
                    columns={visibleColumns}
                    sectionMetaById={sectionMetaById}
                    onToggleSelect={onToggleSelect}
                    onOpenDetail={onOpenDetail}
                    onSingleLaunch={onSingleLaunch}
                    onManualPass={onManualPass}
                    onCancel={onCancel}
                    onRestore={onRestore}
                    onSoftDelete={onSoftDelete}
                    onSkuClick={onSkuClick}
                  />
                )}
              />
            </table>
            </div>
            {rows.length === 0 && !isLoading && (
              <p className="p-4 text-sm text-muted-foreground text-center">Нет строк по выбранному фильтру</p>
            )}
            <TablePaginationFooter
              page={page}
              totalPages={totalPages}
              total={total}
              shownCount={rows.length}
              limit={limit}
              onPageChange={onPageChange}
              onLimitChange={onLimitChange}
              rangeLabel={rangeLabel}
            />
          </div>
        </section>
      </div>
    </>
  );
}
