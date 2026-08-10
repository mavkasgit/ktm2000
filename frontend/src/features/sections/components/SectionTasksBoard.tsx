/**
 * components/SectionTasksBoard.tsx
 * =================================
 * Доска задач одного участка производства.
 *
 * Сохраняет весь старый функционал (режимы, bulk, действия) +
 * использует новый groupTasksByProfile вместо BoardRowItem.
 */

import { useMemo, useState, useCallback, useEffect, useRef } from "react";
import { ChevronDown, ChevronRight } from "lucide-react";
import type { SectionBoardQueryParams, SectionBoardTask, TaskGroup } from "@/shared/api/shopfloor";
import { formatDimensionsFilterValue, formatDimensionsLabel } from "@/shared/api/stock";
import {
  Badge,
  Button,
  SortableFilterHeader,
  FiltersPanel,
  TableCornerResetCell,
  TableCornerResetHeader,
  TablePaginationFooter,
  VirtualizedTableBody,
  DATA_TABLE_STYLES,
  buildActiveFilterSummary,
  type FiltersPanelField,
} from "@/shared/ui";
import type { ColumnSortDef } from "@/shared/hooks/useTableQueryEngine";
import type { PageLimitOption } from "@/shared/hooks/usePaginatedTableQuery";
import { useFilterableTable } from "@/shared/hooks/useFilterableTable";
import { buildColumnFilterPredicate } from "@/shared/lib/columnFilterSearch";
import {
  buildBoardServerQueryParams,
  isServerSortField,
  type TaskSortField,
} from "../lib/boardQueryParams";
import { groupTasksByProfile, groupStatus, sortGroupsByPriority } from "../lib/groupTasksByProfile";
import type { GroupingProfile } from "../lib/groupingProfiles";
import {
  getReadyStatusLabel,
  getStatusLabel,
  getStatusColor,
  isTaskCompletable,
  getCompletionDisabledReason,
  getTaskViewCategory,
  isTaskFullyTransferred,
} from "../lib/taskStatus";
import { TABLE_ROW_STYLES } from "@/shared/lib/tableRowStyles";

// ---------------------------------------------------------------------------
// Экспорты для обратной совместимости
// ---------------------------------------------------------------------------

export type TaskBoardViewMode = {
  active: boolean;
  waiting: boolean;
  completed: boolean;
};
export type TaskActionDialogType = "complete";

export type BulkSelectionController = {
  selectedIds: Set<number>;
  isSelected: (id: number) => boolean;
  selectOne: (id: number, checked?: boolean) => void;
  selectedCount: number;
  isAllSelected: (ids: Iterable<number>) => boolean;
  isIndeterminate: (ids: Iterable<number>) => boolean;
  selectAllFiltered: (ids: Iterable<number>) => void;
  clear: () => void;
};

// ---------------------------------------------------------------------------
// Внутренние типы
// ---------------------------------------------------------------------------

const CLIENT_FILTER_FIELDS: TaskSortField[] = [
  "plannedQty",
  "issuedQty",
  "completedQty",
  "transferredQty",
  "rejectedQty",
  "remainingQty",
  "status",
];

function pickClientFilterState<Field extends string>(
  columnFilters: Partial<Record<Field, Set<string>>>,
  columnSearchQueries: Partial<Record<Field, string>>,
  fields: readonly Field[],
) {
  const nextFilters: Partial<Record<Field, Set<string>>> = {};
  const nextSearches: Partial<Record<Field, string>> = {};
  for (const field of fields) {
    if (columnFilters[field]) nextFilters[field] = columnFilters[field];
    if (columnSearchQueries[field]) nextSearches[field] = columnSearchQueries[field];
  }
  return { columnFilters: nextFilters, columnSearchQueries: nextSearches };
}

function fmtQty(value: string): string {
  const n = parseFloat(value);
  if (!Number.isFinite(n)) return "0";
  return String(Math.round(n));
}

function isTaskVisible(task: SectionBoardTask, mode: TaskBoardViewMode): boolean {
  const category = getTaskViewCategory(task);
  if (mode.active && category === "active") return true;
  if (mode.waiting && category === "waiting") return true;
  if (mode.completed && category === "completed") return true;
  return false;
}

function getStatusPriority(task: SectionBoardTask): number {
  const category = getTaskViewCategory(task);
  if (category === "active") return 0;
  if (category === "waiting") return 1;
  if (category === "completed") return 2;
  return 3;
}

function getRowStatusClass(task: SectionBoardTask, isSelected: boolean, isInGroup: boolean): string {
  if (isSelected) return TABLE_ROW_STYLES.selectedRow;

  const category = getTaskViewCategory(task);
  const status = task.status;
  const isWaiting = category === "waiting";
  const isActive = category === "active";
  const isCompleted = category === "completed";

  if (isWaiting) {
    return "bg-background hover:bg-slate-50 transition-colors border-l-4 border-l-yellow-400 text-slate-800";
  }
  if (isActive) {
    if (["in_progress", "in_work"].includes(status)) {
      return "bg-amber-50/30 hover:bg-amber-50/70 border-l-4 border-l-amber-400 text-slate-900 font-medium";
    }
    return "bg-blue-50/20 hover:bg-blue-50/50 border-l-4 border-l-blue-400 text-slate-900";
  }
  if (isCompleted) {
    return "bg-emerald-50/10 text-emerald-700/80 line-through decoration-slate-300 hover:bg-emerald-50/30 border-l-4 border-l-emerald-300 opacity-60";
  }

  return isInGroup ? TABLE_ROW_STYLES.defaultGroupRow : TABLE_ROW_STYLES.defaultRow;
}

function getMobileCardStatusClass(task: SectionBoardTask, isSelected: boolean): string {
  if (isSelected) return TABLE_ROW_STYLES.selectedMobileCard;

  const category = getTaskViewCategory(task);
  const status = task.status;
  const isWaiting = category === "waiting";
  const isActive = category === "active";
  const isCompleted = category === "completed";

  if (isWaiting) {
    return "border border-slate-200 bg-background text-slate-800 rounded-lg border-l-4 border-l-yellow-400";
  }
  if (isActive) {
    if (["in_progress", "in_work"].includes(status)) {
      return "border border-amber-200 bg-amber-50/30 text-slate-900 rounded-lg border-l-4 border-l-amber-400";
    }
    return "border border-blue-200 bg-blue-50/20 text-slate-900 rounded-lg border-l-4 border-l-blue-400";
  }
  if (isCompleted) {
    return "border border-emerald-100 bg-emerald-50/10 text-slate-400 opacity-60 rounded-lg border-l-4 border-l-emerald-300 line-through decoration-slate-300";
  }
  return "border border-slate-200 rounded-lg bg-card text-card-foreground";
}

function getTaskCellValue(task: SectionBoardTask, field: TaskSortField): string {
  switch (field) {
    case "sequence": return String(task.sequence);
    case "productSku": return task.product_sku;
    case "dimensions": return formatDimensionsLabel(task.dimensions);
    case "status": return getStatusLabel(task);
    case "plannedQty": return String(parseFloat(task.planned_quantity) || 0);
    case "issuedQty": return String(parseFloat(task.cache.issued_quantity) || 0);
    case "completedQty": return String(parseFloat(task.cache.completed_quantity) || 0);
    case "transferredQty": return String(parseFloat(task.cache.transferred_quantity) || 0);
    case "rejectedQty": return String(parseFloat(task.cache.rejected_quantity) || 0);
    case "remainingQty": return String(parseFloat(task.cache.remaining_quantity) || 0);
  }
}

function StatusDot({ task }: { task: SectionBoardTask }) {
  const status = task.status;
  let colorClass = "bg-slate-300";
  if (["in_progress", "in_work"].includes(status)) {
    colorClass = "bg-amber-500 animate-pulse";
  } else if (["ready", "partially_completed", "partially"].includes(status)) {
    colorClass = status === "ready" && getReadyStatusLabel(task) === "Не передано"
      ? "bg-slate-400"
      : "bg-blue-500";
  } else if (["completed", "done"].includes(status) || isTaskFullyTransferred(task)) {
    colorClass = "bg-emerald-500";
  } else if (status === "blocked") {
    colorClass = "bg-red-500";
  } else if (["waiting_previous", "pending"].includes(status)) {
    colorClass = "bg-yellow-400";
  }
  return (
    <span className={`inline-block h-2.5 w-2.5 rounded-full ${colorClass}`} title={getStatusLabel(task)} />
  );
}

/** Компактный прогресс по выходам трансформирующего задания (ADR-0002). */
function renderOutputsProgress(task: SectionBoardTask, className: string) {
  if (!task.transforms_dimensions || !task.outputs_progress?.length) return null;
  const text = task.outputs_progress
    .map((row) => `${formatDimensionsLabel(row.dimensions)}: ${fmtQty(row.produced_quantity)}/${fmtQty(row.quantity)}`)
    .join(" · ");
  return (
    <span className={className} title={text}>
      {text}
    </span>
  );
}

function renderTaskRow(
  task: SectionBoardTask,
  isSelected: boolean | undefined,
  bulkMode: boolean | undefined,
  bulkSelection: BulkSelectionController | undefined,
  onAction: (type: TaskActionDialogType, task: SectionBoardTask) => void,
  isLastInGroup = false,
  isInGroup = false,
) {
  const buttonBase = "min-h-[32px] transition-all";
  const buttonDefault = "hover:bg-accent/50";

  const handleAction = (type: TaskActionDialogType) => {
    onAction(type, task);
  };
  return (
    <tr
      key={task.id}
      className={`cursor-pointer transition-colors ${getRowStatusClass(task, !!isSelected, isInGroup)} ${isLastInGroup ? "border-b-2 border-blue-300" : "border-b"}`}
      onClick={() => {
        if (bulkMode && bulkSelection && task.status !== "waiting_previous") {
          bulkSelection.selectOne(task.id);
        }
      }}
    >
      <td className="p-2 text-center">
        <StatusDot task={task} />
      </td>
      <td className="p-2 font-medium">{task.product_sku}</td>
      <td className="p-2 text-xs text-muted-foreground">{formatDimensionsLabel(task.dimensions)}</td>
      <td className="p-2">
        {task.operation_names && task.operation_names.length > 1 ? (
          <span className="text-xs font-medium">{task.operation_names.join(" + ")}</span>
        ) : (
          <span className="text-xs">{task.operation_name || "—"}</span>
        )}
        {task.operation_summary && (
          <span className="block text-xs text-muted-foreground" title={task.operation_summary}>
            {task.operation_summary}
          </span>
        )}
        {renderOutputsProgress(task, "block text-xs text-muted-foreground tabular-nums")}
      </td>
      <td className="p-2">{fmtQty(task.planned_quantity)}</td>
      <td className="p-2">{fmtQty(task.cache.issued_quantity)}</td>
      <td className="p-2">{fmtQty(task.cache.completed_quantity)}</td>
      <td className="p-2">{fmtQty(task.cache.rejected_quantity)}</td>
      <td className="p-2">{fmtQty(task.cache.transferred_quantity)}</td>
      <td className="p-2">{fmtQty(task.cache.remaining_quantity)}</td>
      <td className="p-2">
        <Badge variant="secondary" className={getStatusColor(task)}>
          {getStatusLabel(task)}
        </Badge>
      </td>
      <td className="p-2">
        {task.previous_stage ? (
          <div className="text-xs">
            <div>Годные: <span className="font-medium">{fmtQty(task.previous_stage.completed_quantity)}</span></div>
            <div>Передано: <span className="font-medium">{fmtQty(task.previous_stage.transferred_quantity)}</span></div>
          </div>
        ) : (
          <span className="text-xs text-muted-foreground">—</span>
        )}
      </td>
      <td className="p-2">
        <Button
          size="sm"
          variant="outline"
          className={`${buttonBase} ${buttonDefault}`}
          onClick={() => handleAction("complete")}
          disabled={!isTaskCompletable(task)}
          title={getCompletionDisabledReason(task) ?? "Завершить задачу"}
        >
          <span>Завершить</span>
        </Button>
      </td>
      <TableCornerResetCell />
    </tr>
  );
}

function renderMobileCard(
  task: SectionBoardTask,
  isSelected: boolean | undefined,
  bulkMode: boolean | undefined,
  bulkSelection: BulkSelectionController | undefined,
  onAction: (type: TaskActionDialogType, task: SectionBoardTask) => void,
  isLastInGroup = false,
) {
  const buttonBase = "flex-1 min-h-[36px] transition-all";
  const buttonDefault = "hover:bg-accent/50";

  const handleAction = (type: TaskActionDialogType) => {
    onAction(type, task);
  };
  return (
    <div
      key={task.id}
      className={`p-4 space-y-3 cursor-pointer transition-colors ${getMobileCardStatusClass(task, !!isSelected)} ${isLastInGroup ? "border-b-2 border-blue-300 mb-3" : "mb-0"}`}
      onClick={() => {
        if (bulkMode && bulkSelection && task.status !== "waiting_previous") {
          bulkSelection.selectOne(task.id);
        }
      }}
    >
      <div className="flex items-center justify-between gap-2">
        <div className="flex items-center gap-2 font-semibold">
          <StatusDot task={task} />
          <span className="text-sm font-medium">{task.product_sku}</span>
        </div>
        <Badge variant="secondary" className={getStatusColor(task)}>
          {getStatusLabel(task)}
        </Badge>
      </div>

      <div className="grid grid-cols-2 gap-2 text-sm">
        <div><span className="text-muted-foreground">План:</span> {fmtQty(task.planned_quantity)}</div>
        <div><span className="text-muted-foreground">Размер:</span> {formatDimensionsLabel(task.dimensions)}</div>
        <div><span className="text-muted-foreground">Операция:</span> {task.operation_names && task.operation_names.length > 1 ? task.operation_names.join(" + ") : (task.operation_name || "—")}</div>
        <div><span className="text-muted-foreground">Выдано:</span> {fmtQty(task.cache.issued_quantity)}</div>
        <div><span className="text-muted-foreground">Годные:</span> {fmtQty(task.cache.completed_quantity)}</div>
        <div><span className="text-muted-foreground">Брак:</span> {fmtQty(task.cache.rejected_quantity)}</div>
        <div><span className="text-muted-foreground">Передано:</span> {fmtQty(task.cache.transferred_quantity)}</div>
        <div><span className="text-muted-foreground">Остаток:</span> {fmtQty(task.cache.remaining_quantity)}</div>
      </div>

      {task.operation_summary ? (
        <div className="text-xs text-muted-foreground border-t pt-2" title={task.operation_summary}>
          {task.operation_summary}
        </div>
      ) : null}

      {renderOutputsProgress(task, "block text-xs text-muted-foreground tabular-nums border-t pt-2")}

      {task.previous_stage ? (
        <div className="text-xs text-muted-foreground border-t pt-2">
          Пред. этап: годные {fmtQty(task.previous_stage.completed_quantity)}, передано {fmtQty(task.previous_stage.transferred_quantity)}
        </div>
      ) : null}

      <div className="flex gap-2 pt-1">
        <Button
          size="sm"
          variant="outline"
          className={`${buttonBase} ${buttonDefault}`}
          onClick={() => handleAction("complete")}
          disabled={!isTaskCompletable(task)}
          title={getCompletionDisabledReason(task) ?? "Завершить задачу"}
        >
          <span>Завершить</span>
        </Button>
      </div>
    </div>
  );
}

// ---------------------------------------------------------------------------
// TaskGroupRow для таблицы (адаптер)
// ---------------------------------------------------------------------------

function TableTaskGroupRow({
  group,
  isCollapsed,
  isBulkMode,
  bulkSelection,
  onToggleCollapse,
  onSelectGroup,
  onCompleteGroup,
}: {
  group: ReturnType<typeof groupTasksByProfile>[number];
  isCollapsed: boolean;
  isBulkMode: boolean;
  bulkSelection?: BulkSelectionController;
  onToggleCollapse: () => void;
  onSelectGroup: () => void;
  onCompleteGroup?: (group: TaskGroup) => void;
}) {
  const taskIds = group.tasks.map((t) => t.id);
  const allSelected = bulkSelection?.isAllSelected(taskIds) ?? false;
  const firstTask = group.tasks[0];
  const groupHasCompletable = group.tasks.some(isTaskCompletable);

  return (
    <tr
      className={`border-y border-slate-200 cursor-pointer transition-colors font-semibold ${isBulkMode && allSelected ? TABLE_ROW_STYLES.selectedGroupHeader : TABLE_ROW_STYLES.defaultGroupHeader}`}
      onClick={() => {
        if (isBulkMode) onSelectGroup();
        else onToggleCollapse();
      }}
    >
      <td className="p-2 text-center">
        <div className="flex items-center justify-center">
          <button
            className="p-1 hover:bg-slate-200 rounded transition-colors text-slate-500 hover:text-slate-800"
            onClick={(e) => {
              e.stopPropagation();
              onToggleCollapse();
            }}
            title={isCollapsed ? "Раскрыть" : "Скрыть"}
          >
            {isCollapsed ? (
              <ChevronRight className="h-4 w-4 shrink-0" />
            ) : (
              <ChevronDown className="h-4 w-4 shrink-0" />
            )}
          </button>
        </div>
      </td>
      <td className="p-2 text-slate-900">
        {firstTask.product_sku}
      </td>
      <td className="p-2 text-xs text-slate-500 font-medium">
        {formatDimensionsLabel(firstTask.dimensions)}
      </td>
      <td className="p-2 text-xs text-slate-500 font-medium">
        {firstTask.operation_name || "—"}
      </td>
      <td className="p-2 text-slate-700">{fmtQty(String(group.totalQtyPlan))}</td>
      <td className="p-2 text-slate-700">{fmtQty(String(group.tasks.reduce((s, t) => s + parseFloat(t.cache.issued_quantity), 0)))}</td>
      <td className="p-2 text-slate-700">{fmtQty(String(group.totalQtyDone))}</td>
      <td className="p-2 text-slate-700">{fmtQty(String(group.tasks.reduce((s, t) => s + parseFloat(t.cache.rejected_quantity), 0)))}</td>
      <td className="p-2 text-slate-700">{fmtQty(String(group.tasks.reduce((s, t) => s + parseFloat(t.cache.transferred_quantity), 0)))}</td>
      <td className="p-2 text-slate-700">{fmtQty(String(group.tasks.reduce((s, t) => s + parseFloat(t.cache.remaining_quantity), 0)))}</td>
      <td className="p-2">
        <div className="flex items-center gap-1">
          <Badge variant="secondary" className="font-bold">
            &times;{group.tasks.length}
          </Badge>
          {isBulkMode && allSelected && (
            <span className={`text-xs ${TABLE_ROW_STYLES.selectedLabel}`}>выбрано</span>
          )}
        </div>
      </td>
      <td className={`p-2 text-xs text-muted-foreground ${isBulkMode && allSelected ? TABLE_ROW_STYLES.selectedGroupHeader : TABLE_ROW_STYLES.defaultGroupRow}`}>—</td>
      <td className={`p-2 ${isBulkMode && allSelected ? TABLE_ROW_STYLES.selectedGroupHeader : TABLE_ROW_STYLES.defaultGroupRow}`}>
        {onCompleteGroup && (
          <Button
            size="sm"
            variant="outline"
            className="min-h-[32px] transition-all hover:bg-accent/50"
            onClick={(e) => {
              e.stopPropagation();
              onCompleteGroup(group);
            }}
            disabled={!groupHasCompletable}
            title={groupHasCompletable ? "Открыть панель завершения группы" : "Все задания в группе завершены"}
          >
            <span>Завершить группу</span>
          </Button>
        )}
      </td>
      <TableCornerResetCell />
    </tr>
  );
}

// ---------------------------------------------------------------------------
// Props
// ---------------------------------------------------------------------------

type SectionTasksBoardProps = {
  tasks: SectionBoardTask[];
  total: number;
  isLoading: boolean;
  mode: TaskBoardViewMode;
  onModeChange: (next: TaskBoardViewMode) => void;
  onAction: (type: TaskActionDialogType, task: SectionBoardTask) => void;
  bulkMode?: boolean;
  onBulkModeChange?: (enabled: boolean) => void;
  bulkSelection?: BulkSelectionController;
  profile: GroupingProfile;
  onSelectAllVisible?: (ids: number[]) => void;
  onCompleteGroup?: (group: TaskGroup) => void;
  page: number;
  setPage: (page: number) => void;
  limit: PageLimitOption;
  setLimit: (limit: PageLimitOption) => void;
  totalPages: number;
  rangeLabel: string;
  onServerQueryChange: (
    query: Pick<SectionBoardQueryParams, "search" | "product_sku" | "sort_by" | "sort_order">,
  ) => void;
};

type VirtualBoardRow =
  | {
      kind: "group";
      key: string;
      group: ReturnType<typeof groupTasksByProfile>[number];
      isCollapsed: boolean;
    }
  | {
      kind: "task";
      key: string;
      task: SectionBoardTask;
      isLastInGroup: boolean;
      isInGroup: boolean;
    };

// ---------------------------------------------------------------------------
// Компонент
// ---------------------------------------------------------------------------

export function SectionTasksBoard({
  tasks,
  total,
  isLoading,
  mode,
  onModeChange,
  onAction,
  bulkMode,
  onBulkModeChange,
  bulkSelection,
  profile,
  onSelectAllVisible,
  onCompleteGroup,
  page,
  setPage,
  limit,
  setLimit,
  totalPages,
  rangeLabel,
  onServerQueryChange,
}: SectionTasksBoardProps) {
  const tableScrollRef = useRef<HTMLDivElement>(null);
  const [searchQuery, setSearchQuery] = useState("");
  const [debouncedSearch, setDebouncedSearch] = useState("");
  const {
    bindColumn,
    columnFilters,
    columnSearchQueries,
    sortConfigs,
    handleSort: handleSortChange,
    resetAll: resetAllFilters,
    hasActiveFilters: hasTableFiltersActive,
  } = useFilterableTable<TaskSortField>({
    extraHasActive: searchQuery.trim().length > 0,
  });

  useEffect(() => {
    const timer = window.setTimeout(() => setDebouncedSearch(searchQuery), 300);
    return () => window.clearTimeout(timer);
  }, [searchQuery]);

  useEffect(() => {
    onServerQueryChange(
      buildBoardServerQueryParams({
        search: debouncedSearch,
        columnFilters,
        columnSearchQueries,
        sortConfigs,
      }),
    );
  }, [debouncedSearch, columnFilters, columnSearchQueries, sortConfigs, onServerQueryChange]);

  const clientFilterState = useMemo(
    () => pickClientFilterState(columnFilters, columnSearchQueries, CLIENT_FILTER_FIELDS),
    [columnFilters, columnSearchQueries],
  );

  const clientFilterPredicate = useMemo(
    () =>
      buildColumnFilterPredicate({
        ...clientFilterState,
        getCellValue: getTaskCellValue,
      }),
    [clientFilterState],
  );

  const visibleTasks = useMemo(() => {
    let result = tasks.filter((task) => isTaskVisible(task, mode));
    if (clientFilterPredicate) {
      result = result.filter(clientFilterPredicate);
    }
    return result;
  }, [tasks, mode, clientFilterPredicate]);

  const sortDefs: ColumnSortDef<SectionBoardTask, TaskSortField>[] = useMemo(() => [
    { field: "sequence", getSortValue: (t) => t.sequence },
    { field: "productSku", getSortValue: (t) => t.product_sku },
    { field: "status", getSortValue: (t) => t.status },
    { field: "plannedQty", getSortValue: (t) => parseFloat(t.planned_quantity) || 0 },
    { field: "issuedQty", getSortValue: (t) => parseFloat(t.cache.issued_quantity) || 0 },
    { field: "completedQty", getSortValue: (t) => parseFloat(t.cache.completed_quantity) || 0 },
    { field: "transferredQty", getSortValue: (t) => parseFloat(t.cache.transferred_quantity) || 0 },
    { field: "rejectedQty", getSortValue: (t) => parseFloat(t.cache.rejected_quantity) || 0 },
    { field: "remainingQty", getSortValue: (t) => parseFloat(t.cache.remaining_quantity) || 0 },
  ], []);

  const uniqueValues = useMemo(() => ({
    sequence: [...new Set(visibleTasks.map((t) => String(t.sequence)))],
    productSku: [...new Set(visibleTasks.map((t) => t.product_sku))],
    dimensions: [...new Set(visibleTasks.map((t) => JSON.stringify(t.dimensions ?? null)))].sort(
      (a, b) => formatDimensionsFilterValue(a).localeCompare(formatDimensionsFilterValue(b), "ru"),
    ),
    status: [...new Set(visibleTasks.map((t) => getStatusLabel(t)))],
    plannedQty: [...new Set(visibleTasks.map((t) => String(parseFloat(t.planned_quantity) || 0)))],
    issuedQty: [...new Set(visibleTasks.map((t) => String(parseFloat(t.cache.issued_quantity) || 0)))],
    completedQty: [...new Set(visibleTasks.map((t) => String(parseFloat(t.cache.completed_quantity) || 0)))],
    transferredQty: [...new Set(visibleTasks.map((t) => String(parseFloat(t.cache.transferred_quantity) || 0)))],
    rejectedQty: [...new Set(visibleTasks.map((t) => String(parseFloat(t.cache.rejected_quantity) || 0)))],
    remainingQty: [...new Set(visibleTasks.map((t) => String(parseFloat(t.cache.remaining_quantity) || 0)))],
  }), [visibleTasks]);

  const sortedTasks = useMemo(() => {
    const activeSort = sortConfigs[0];
    if (!activeSort || isServerSortField(activeSort.field)) {
      return visibleTasks;
    }
    const def = sortDefs.find((item) => item.field === activeSort.field);
    if (!def) return visibleTasks;
    return [...visibleTasks].sort((a, b) => {
      const left = def.getSortValue(a);
      const right = def.getSortValue(b);
      if (left === right) return 0;
      const cmp = left < right ? -1 : 1;
      return activeSort.order === "asc" ? cmp : -cmp;
    });
  }, [visibleTasks, sortConfigs, sortDefs]);

  const groups = useMemo(() => {
    const grouped = groupTasksByProfile(sortedTasks, profile);
    
    // Sort tasks inside each group by status priority, then by sequence
    for (const g of grouped) {
      g.tasks.sort((a, b) => {
        const pA = getStatusPriority(a);
        const pB = getStatusPriority(b);
        if (pA !== pB) return pA - pB;
        return a.sequence - b.sequence;
      });
    }

    // Split groups into active/waiting and completed, preserving user's sorting order
    const activeOrWaiting: typeof grouped = [];
    const completed: typeof grouped = [];

    for (const g of grouped) {
      const isCompleted = g.tasks.every((t) => getStatusPriority(t) >= 2);
      if (isCompleted) {
        completed.push(g);
      } else {
        activeOrWaiting.push(g);
      }
    }

    return [...activeOrWaiting, ...completed];
  }, [sortedTasks, profile]);

  // Группы по умолчанию свёрнуты; пользователь может раскрыть любую вручную.
  // Сохраняем развёрнутые пользователем ключи, остальные — свернуты.
  const [manuallyExpanded, setManuallyExpanded] = useState<Set<string>>(new Set());
  const collapsedGroups = useMemo(() => {
    const collapsed = new Set<string>();
    for (const g of groups) {
      if (g.tasks.length > 1 && !manuallyExpanded.has(g.key)) {
        collapsed.add(g.key);
      }
    }
    return collapsed;
  }, [groups, manuallyExpanded]);

  const toggleGroup = useCallback((groupKey: string) => {
    setManuallyExpanded((prev) => {
      const next = new Set(prev);
      if (next.has(groupKey)) next.delete(groupKey);
      else next.add(groupKey);
      return next;
    });
  }, []);

  const statusLabel = (label: string) => label;

  const modeCounts = useMemo(() => ({
    active: tasks.filter((t) => getTaskViewCategory(t) === "active").length,
    waiting: tasks.filter((t) => getTaskViewCategory(t) === "waiting").length,
    completed: tasks.filter((t) => getTaskViewCategory(t) === "completed").length,
  }), [tasks]);

  const modeFields = useMemo((): FiltersPanelField[] => [
    {
      kind: "search",
      key: "search",
      value: searchQuery,
      onChange: setSearchQuery,
      placeholder: "Поиск",
      layoutSpan: "min-w-[250px]",
    },
    {
      kind: "bulk",
      key: "bulk-mode",
      enabled: bulkMode ?? false,
      onChange: (enabled: boolean) => onBulkModeChange?.(enabled),
    },
    {
      kind: "toggle",
      key: "mode-active",
      label: "Активные",
      badgeCount: modeCounts.active,
      checked: mode.active,
      onChange: () => onModeChange({ ...mode, active: !mode.active }),
      layoutSpan: "min-w-[0px]",
    },
    {
      kind: "toggle",
      key: "mode-waiting",
      label: "Ожидают",
      badgeCount: modeCounts.waiting,
      checked: mode.waiting,
      onChange: () => onModeChange({ ...mode, waiting: !mode.waiting }),
      layoutSpan: "min-w-[0px]",
    },
    {
      kind: "toggle",
      key: "mode-completed",
      label: "Завершенные",
      badgeCount: modeCounts.completed,
      checked: mode.completed,
      onChange: () => onModeChange({ ...mode, completed: !mode.completed }),
      layoutSpan: "min-w-[0px]",
    },
  ], [mode, onModeChange, searchQuery, bulkMode, onBulkModeChange, modeCounts]);

  const handleResetAllFilters = useCallback(() => {
    setSearchQuery("");
    setDebouncedSearch("");
    resetAllFilters();
    bulkSelection?.clear();
    onBulkModeChange?.(false);
    setPage(1);
  }, [resetAllFilters, bulkSelection, onBulkModeChange, setPage]);

  const virtualRows = useMemo((): VirtualBoardRow[] => {
    const items: VirtualBoardRow[] = [];
    for (const group of groups) {
      if (group.tasks.length === 1) {
        const task = group.tasks[0];
        items.push({
          kind: "task",
          key: `task-${task.id}`,
          task,
          isLastInGroup: true,
          isInGroup: false,
        });
        continue;
      }

      const isCollapsed = collapsedGroups.has(group.key);
      items.push({
        kind: "group",
        key: `group-${group.key}`,
        group,
        isCollapsed,
      });
      if (!isCollapsed) {
        group.tasks.forEach((task, idx) => {
          items.push({
            kind: "task",
            key: `task-${task.id}`,
            task,
            isLastInGroup: idx === group.tasks.length - 1,
            isInGroup: true,
          });
        });
      }
    }
    return items;
  }, [groups, collapsedGroups]);

  const renderVirtualRow = useCallback(
    (row: VirtualBoardRow) => {
      if (row.kind === "group") {
        return (
          <TableTaskGroupRow
            key={row.key}
            group={row.group}
            isCollapsed={row.isCollapsed}
            isBulkMode={!!bulkMode}
            bulkSelection={bulkSelection}
            onToggleCollapse={() => toggleGroup(row.group.key)}
            onCompleteGroup={onCompleteGroup}
            onSelectGroup={() => {
              if (!bulkMode || !bulkSelection) return;
              const taskIds = row.group.tasks.map((t) => t.id);
              const allSelected = bulkSelection.isAllSelected(taskIds);
              const someSelected = bulkSelection.isIndeterminate(taskIds);
              if (allSelected || someSelected) {
                for (const id of taskIds) {
                  bulkSelection.selectOne(id, false);
                }
              } else {
                for (const id of taskIds) {
                  bulkSelection.selectOne(id, true);
                }
              }
            }}
          />
        );
      }

      const isSelected = bulkMode && bulkSelection?.isSelected(row.task.id);
      return renderTaskRow(
        row.task,
        isSelected,
        bulkMode,
        bulkSelection,
        onAction,
        row.isLastInGroup,
        row.isInGroup,
      );
    },
    [bulkMode, bulkSelection, onAction, onCompleteGroup, toggleGroup],
  );

  const headerCellClass = `${DATA_TABLE_STYLES.headerRow} ${DATA_TABLE_STYLES.headerCell}`;

  const activeFilterSummary = useMemo(
    () =>
      buildActiveFilterSummary({}, searchQuery, sortConfigs.length, {
        columnFilters,
        columnSearchQueries,
        columnLabels: {
          sequence: "№",
          productSku: "Артикул",
          status: "Статус",
          plannedQty: "План",
          issuedQty: "Выдано",
          completedQty: "Готово",
          transferredQty: "Передано",
          rejectedQty: "Брак",
          remainingQty: "Остаток",
        },
      }),
    [searchQuery, sortConfigs.length, columnFilters, columnSearchQueries],
  );

  return (
    <div className="space-y-3">
      <FiltersPanel
        compact
        fields={modeFields}
        activeSummary={activeFilterSummary}
        onSelectAll={() => {
          onBulkModeChange?.(true);
          onSelectAllVisible?.(visibleTasks.filter((t) => t.status !== "waiting_previous").map((t) => t.id));
        }}
        totalRowCount={total}
      />

      {isLoading && <div className="rounded-lg border p-4 text-sm text-muted-foreground">Загрузка задач...</div>}
      {!isLoading && total === 0 && (
        <div className="rounded-lg border p-4 text-sm text-muted-foreground text-center">
          Нет задач в выбранном режиме
        </div>
      )}

      {!isLoading && total > 0 && (
        <>
          {/* Desktop table */}
          <div className={`hidden md:block ${DATA_TABLE_STYLES.container}`}>
            <div
              ref={tableScrollRef}
              className="overflow-auto"
              style={{ maxHeight: "70vh" }}
            >
            <table className="w-full border-separate border-spacing-0 text-sm">
              <thead>
                <tr>
                  <th className={`${headerCellClass} w-12 text-center`}>
                    <span className="text-xs font-medium text-muted-foreground">Статус</span>
                  </th>
                  <th className={`${headerCellClass} p-0 text-left`}>
                    <SortableFilterHeader
                      field="productSku"
                      label="Артикул"
                      currentSorts={sortConfigs}
                      onSortChange={handleSortChange}
                      values={uniqueValues.productSku}
                      {...bindColumn("productSku")}
                    />
                  </th>
                  <th className={`${headerCellClass} p-0 text-left`}>
                    <SortableFilterHeader
                      field="dimensions"
                      label="Размер"
                      currentSorts={sortConfigs}
                      onSortChange={handleSortChange}
                      values={uniqueValues.dimensions}
                      selectedValues={bindColumn("dimensions").selectedValues}
                      onFilterChange={bindColumn("dimensions").onFilterChange}
                      valueLabel={formatDimensionsFilterValue}
                    />
                  </th>
                  <th className={`${headerCellClass} text-left`}>
                    <span className="text-xs font-medium text-muted-foreground">Операция</span>
                  </th>
                  <th className={`${headerCellClass} p-0 text-left`}>
                    <SortableFilterHeader
                      field="plannedQty"
                      label="План"
                      currentSorts={sortConfigs}
                      onSortChange={handleSortChange}
                      values={uniqueValues.plannedQty}
                      {...bindColumn("plannedQty")}
                    />
                  </th>
                  <th className={`${headerCellClass} p-0 text-left`}>
                    <SortableFilterHeader
                      field="issuedQty"
                      label="Выдано"
                      currentSorts={sortConfigs}
                      onSortChange={handleSortChange}
                      values={uniqueValues.issuedQty}
                      {...bindColumn("issuedQty")}
                    />
                  </th>
                  <th className={`${headerCellClass} p-0 text-left`}>
                    <SortableFilterHeader
                      field="completedQty"
                      label="Годные"
                      currentSorts={sortConfigs}
                      onSortChange={handleSortChange}
                      values={uniqueValues.completedQty}
                      {...bindColumn("completedQty")}
                    />
                  </th>
                  <th className={`${headerCellClass} p-0 text-left`}>
                    <SortableFilterHeader
                      field="rejectedQty"
                      label="Брак"
                      currentSorts={sortConfigs}
                      onSortChange={handleSortChange}
                      values={uniqueValues.rejectedQty}
                      {...bindColumn("rejectedQty")}
                    />
                  </th>
                  <th className={`${headerCellClass} p-0 text-left`}>
                    <SortableFilterHeader
                      field="transferredQty"
                      label="Передано"
                      currentSorts={sortConfigs}
                      onSortChange={handleSortChange}
                      values={uniqueValues.transferredQty}
                      {...bindColumn("transferredQty")}
                    />
                  </th>
                  <th className={`${headerCellClass} p-0 text-left`}>
                    <SortableFilterHeader
                      field="remainingQty"
                      label="Остаток"
                      currentSorts={sortConfigs}
                      onSortChange={handleSortChange}
                      values={uniqueValues.remainingQty}
                      {...bindColumn("remainingQty")}
                    />
                  </th>
                  <th className={`${headerCellClass} p-0 text-left`}>
                    <SortableFilterHeader
                      field="status"
                      label="Статус"
                      currentSorts={sortConfigs}
                      onSortChange={handleSortChange}
                      values={uniqueValues.status}
                      {...bindColumn("status")}
                      valueLabel={statusLabel}
                    />
                  </th>
                  <th className={`${headerCellClass} text-left`}>
                    <span className="text-xs font-medium text-muted-foreground">Пред. этап</span>
                  </th>
                  <th className={`${headerCellClass} text-left`}>
                    <span className="text-xs font-medium text-muted-foreground">Действия</span>
                  </th>
                  <TableCornerResetHeader
                    hasActiveFilters={hasTableFiltersActive}
                    onReset={handleResetAllFilters}
                    dataTableHeader
                  />
                </tr>
              </thead>
              {sortedTasks.length === 0 ? (
                <tbody>
                  <tr>
                    <td colSpan={14} className="p-8 text-center text-sm text-muted-foreground">
                      Нет задач, соответствующих фильтру
                    </td>
                  </tr>
                </tbody>
              ) : (
                <VirtualizedTableBody
                  rows={virtualRows}
                  rowHeight={48}
                  colSpan={13}
                  scrollContainerRef={tableScrollRef}
                  renderRow={(row) => renderVirtualRow(row)}
                />
              )}
            </table>
            </div>
          </div>

          {/* Mobile cards */}
          <div className="md:hidden space-y-3">
            {sortedTasks.length === 0 ? (
              <div className="rounded-lg border p-4 text-sm text-muted-foreground text-center">
                Нет задач, соответствующих фильтру
              </div>
            ) : groups.map((group) => {
              const isCollapsed = collapsedGroups.has(group.key);
              const isSingleTask = group.tasks.length === 1;

              // Одна задача — рендерим напрямую без шапки группы
              if (isSingleTask) {
                const task = group.tasks[0];
                const isSelected = bulkMode && bulkSelection?.isSelected(task.id);
                return renderMobileCard(task, isSelected, bulkMode, bulkSelection, onAction, true);
              }

              return (
                <div key={group.key} className={`rounded-lg overflow-hidden transition-colors ${bulkMode && bulkSelection?.isAllSelected(group.tasks.map(t => t.id)) ? TABLE_ROW_STYLES.selectedGroupContainer : TABLE_ROW_STYLES.defaultGroupContainer}`}>
                  <div
                    className="p-3 flex items-center justify-between gap-2 border-b border-muted cursor-pointer"
                    onClick={() => {
                      if (bulkMode && bulkSelection) {
                        const taskIds = group.tasks.map((t) => t.id);
                        const allSelected = bulkSelection.isAllSelected(taskIds);
                        const someSelected = bulkSelection.isIndeterminate(taskIds);
                        if (allSelected || someSelected) {
                          for (const id of taskIds) {
                            bulkSelection.selectOne(id, false);
                          }
                        } else {
                          for (const id of taskIds) {
                            bulkSelection.selectOne(id, true);
                          }
                        }
                      } else {
                        toggleGroup(group.key);
                      }
                    }}
                  >
                    <div className="flex items-center gap-2 min-w-0">
                      <button
                        className="p-0.5 hover:bg-muted/50 rounded transition-colors cursor-pointer"
                        onClick={(e) => {
                          e.stopPropagation();
                          toggleGroup(group.key);
                        }}
                        title={isCollapsed ? "Раскрыть" : "Скрыть"}
                      >
                        {isCollapsed ? (
                          <ChevronRight className="h-4 w-4 text-muted-foreground" />
                        ) : (
                          <ChevronDown className="h-4 w-4 text-muted-foreground" />
                        )}
                      </button>
                      <span className="font-semibold text-sm truncate">
                        {group.label}
                      </span>
                      {bulkMode && bulkSelection?.isAllSelected(group.tasks.map(t => t.id)) && (
                        <span className={`text-xs ${TABLE_ROW_STYLES.selectedLabel} ml-1`}>выбрано</span>
                      )}
                    </div>
                    <div className="flex items-center gap-2 shrink-0">
                      <Badge variant="secondary" className="bg-blue-100 text-blue-700">
                        &times;{group.tasks.length}
                      </Badge>
                      {onCompleteGroup && (() => {
                        const groupHasCompletable = group.tasks.some(isTaskCompletable);
                        return (
                          <Button
                            size="sm"
                            variant="outline"
                            className="min-h-[32px] transition-all hover:bg-accent/50"
                            onClick={(e) => {
                              e.stopPropagation();
                              onCompleteGroup(group);
                            }}
                            disabled={!groupHasCompletable}
                            title={groupHasCompletable ? "Открыть панель завершения группы" : "Все задания в группе завершены"}
                          >
                            <span>Завершить группу</span>
                          </Button>
                        );
                      })()}
                    </div>
                  </div>
                  {!isCollapsed && <div className="divide-y divide-muted">{group.tasks.map((task, idx) => {
                    const isLast = idx === group.tasks.length - 1;
                    const isSelected = bulkMode && bulkSelection?.isSelected(task.id);
                    return renderMobileCard(task, isSelected, bulkMode, bulkSelection, onAction, isLast);
                  })}</div>}
                </div>
              );
            })}
          </div>

          <TablePaginationFooter
            page={page}
            totalPages={totalPages}
            total={total}
            shownCount={visibleTasks.length}
            limit={limit}
            onPageChange={setPage}
            onLimitChange={setLimit}
            rangeLabel={rangeLabel}
          />
        </>
      )}
    </div>
  );
}
