import { ListChecks } from "lucide-react";
import { ProductionPlanningRow } from "@/shared/api/productionPlans";
import { Button, FiltersPanel, VirtualizedTableBody, SortableFilterHeader, type FiltersPanelField } from "@/shared/ui";
import { SortConfig } from "@/shared/hooks/useTableQueryEngine";
import { ExecutionSortField, positionStatusLabels, fmtQty } from "./execution-utils";
import { ExecutionRow } from "./ExecutionRow";
import { getExecutionTableColumns } from "./execution-table-columns";
import {
  BulkPowerBar,
  BulkSelectionTable,
  type BulkActionDefinition,
  type BulkActionResultItem,
  type BulkActionSummary,
  type BulkRunnerProgress,
  type BulkSelectionRow,
  type BulkSelectionAction,
} from "@/shared/bulk";

interface ExecutionTableProps {
  rows: ProductionPlanningRow[];
  filteredRows: ProductionPlanningRow[];
  isLoading: boolean;
  bulkMode: boolean;
  totalRows: number;
  releasedRows: number;
  completedRows: number;
  // filters
  filterFields: FiltersPanelField[];
  resetFilters: () => void;
  activeFilterSummary: { count: number; labels: string[] };
  // sorting
  sortConfigs: SortConfig<ExecutionSortField>[];
  handleSortChange: (field: ExecutionSortField) => void;
  getAriaSort: (field: ExecutionSortField) => "none" | "ascending" | "descending";
  // column filters
  columnFilters: Partial<Record<ExecutionSortField, Set<string>>>;
  onColumnFilterChange: (field: ExecutionSortField, selected: Set<string>) => void;
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
  bulkSelectionRows: BulkSelectionRow[];
  bulkSelectionActions: BulkSelectionAction[];
  bulkProgress: BulkRunnerProgress | null;
  bulkSummary: BulkActionSummary | null;
  selectedBulkActionId: string;
  onActionChange: (id: string) => void;
  executionBulkActions: BulkActionDefinition<number, Map<number, ProductionPlanningRow>>[];
  onRunSelectedBulkAction: () => void;
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
  onOpenHistory: (row: ProductionPlanningRow) => void;
  onToggleSelect: (id: number) => void;
  onRequestBulkSoftDelete: () => void;
  onRemoveSelection?: (id: number) => void;
  tableScrollRef: React.MutableRefObject<HTMLDivElement | null>;
}

export function ExecutionTable({
  rows,
  filteredRows,
  isLoading,
  bulkMode,
  totalRows,
  releasedRows,
  completedRows,
  filterFields,
  resetFilters,
  activeFilterSummary,
  sortConfigs,
  handleSortChange,
  getAriaSort,
  columnFilters,
  onColumnFilterChange,
  uniqueValuesByField,
  hideColumnIds,
  bulkSelection,
  bulkSelectionRows,
  bulkSelectionActions,
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
  onOpenHistory,
  onToggleSelect,
  onRequestBulkSoftDelete,
  onRemoveSelection,
  tableScrollRef,
}: ExecutionTableProps) {
  const visibleColumns = getExecutionTableColumns(hideColumnIds);
  const headerCellClass =
    "sticky top-0 z-20 border-b bg-background p-2 text-left align-middle text-xs font-medium text-muted-foreground overflow-hidden";

  return (
    <>
      {!bulkMode && (
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
      )}

      <div className={bulkMode ? "fixed inset-0 z-50 bg-background flex min-w-0 flex-col overflow-x-hidden overflow-y-auto p-4" : "min-w-0"}>
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
              Выбирайте позиции кликом по строке, используйте фильтры для отбора. Примените действие через кнопки выше. <kbd className="px-1 py-0.5 text-xs rounded bg-muted font-mono">Esc</kbd> — выход.
            </p>
          </div>
        )}

        <section className={bulkMode ? "flex min-h-0 min-w-0 flex-1 flex-col" : "min-w-0 space-y-3"}>
          <FiltersPanel
            compact
            fields={filterFields}
            onReset={resetFilters}
            hasActiveFilters={activeFilterSummary.count > 0}
            activeSummary={activeFilterSummary}
          />

          {!bulkMode && (
            <div className="flex items-center gap-2 mb-2">
              <Button variant="outline" size="sm" onClick={onEnterBulkMode}>
                <ListChecks className="h-4 w-4 mr-1.5" />
                Групповые операции
              </Button>
            </div>
          )}

          {bulkMode && (
            <BulkSelectionTable
              selectedCount={bulkSelection.selectedCount}
              rows={bulkSelectionRows}
              columns={[
                { key: "id", label: "ID" },
                { key: "sku", label: "SKU" },
                { key: "name", label: "Наименование" },
                { key: "qty", label: "Кол-во" },
                { key: "status", label: "Статус" },
              ]}
              actions={bulkSelectionActions}
              onClose={onExitBulkMode}
              onRemoveRow={(id) => {
                bulkSelection.selectOne(Number(id), false);
                onRemoveSelection?.(Number(id));
              }}
              progress={bulkProgress}
              lastSummary={bulkSummary}
              className="shrink-0"
            />
          )}

          {!bulkMode && (
            <BulkPowerBar
              selectedCount={bulkSelection.selectedCount}
              actions={executionBulkActions}
              selectedActionId={selectedBulkActionId}
              onActionChange={onActionChange}
              onRun={onRunSelectedBulkAction}
              onClear={bulkSelection.clear}
              progress={bulkProgress}
              lastSummary={bulkSummary}
              selectedIds={bulkSelection.selectedIds}
              context={rowById}
            />
          )}

          <div
            ref={tableScrollRef}
            className={
              bulkMode
                ? "min-h-0 min-w-0 flex-1 overflow-x-hidden overflow-y-auto rounded-lg border"
                : "min-w-0 max-w-full overflow-x-hidden overflow-y-auto rounded-lg border"
            }
            style={bulkMode ? undefined : { maxHeight: '70vh' }}
          >
            <table className="execution-table w-full table-fixed border-separate border-spacing-0">
              <colgroup>
                {visibleColumns.map((column) => (
                  <col
                    key={column.id}
                    className={column.colClassName}
                    style={{ width: column.width }}
                  />
                ))}
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
                          selectedValues={columnFilters[column.sortField] ?? new Set()}
                          onFilterChange={onColumnFilterChange}
                          valueLabel={column.sortField === "status" ? (v) => positionStatusLabels[v] ?? v : undefined}
                        />
                      ) : (
                        <span className="block truncate">{column.label}</span>
                      )}
                    </th>
                  ))}
                </tr>
              </thead>
              <VirtualizedTableBody
                rows={filteredRows}
                rowHeight={48}
                colSpan={visibleColumns.length}
                scrollContainerRef={tableScrollRef as React.RefObject<HTMLElement | null>}
                renderRow={(row) => (
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
                    onOpenHistory={onOpenHistory}
                  />
                )}
              />
            </table>
            {filteredRows.length === 0 && (
              <p className="p-4 text-sm text-muted-foreground text-center">Нет строк по выбранному фильтру</p>
            )}
          </div>
        </section>
      </div>
    </>
  );
}
