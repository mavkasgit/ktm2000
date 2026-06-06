/**
 * components/SectionTasksBoard.tsx
 * =================================
 * Доска задач одного участка производства.
 *
 * Сохраняет весь старый функционал (режимы, bulk, действия) +
 * использует новый groupTasksByProfile вместо BoardRowItem.
 */

import { useMemo, useState, useCallback } from "react";
import { ChevronDown, ChevronRight } from "lucide-react";
import type { SectionBoardTask, TaskGroup } from "@/shared/api/shopfloor";
import { Badge, Button, SortableFilterHeader, FiltersPanel, type FiltersPanelField } from "@/shared/ui";
import { useTableQueryEngine, SortConfig, ColumnSortDef } from "@/shared/hooks/useTableQueryEngine";
import { nextMultiSortConfigs } from "@/shared/lib/multiSort";
import { groupTasksByProfile, groupStatus, sortGroupsByPriority } from "../lib/groupTasksByProfile";
import type { GroupingProfile } from "../lib/groupingProfiles";
import { TABLE_ROW_STYLES } from "@/shared/lib/tableRowStyles";

// ---------------------------------------------------------------------------
// Экспорты для обратной совместимости
// ---------------------------------------------------------------------------

export type TaskBoardViewMode = "active" | "waiting" | "completed";
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

type TaskSortField =
  | "sequence"
  | "productSku"
  | "plannedQty"
  | "issuedQty"
  | "inWorkQty"
  | "completedQty"
  | "transferredQty"
  | "rejectedQty"
  | "remainingQty"
  | "status";

const taskStatusLabels: Record<string, string> = {
  waiting_previous: "Ожидает",
  ready: "К выдаче",
  in_progress: "В работе",
  partially_completed: "Частично",
  completed: "Завершен",
  cancelled: "Отменен",
  // Новые статусы
  pending: "Ожидает",
  in_work: "В работе",
  done: "Завершен",
  partially: "Частично",
  blocked: "Блокировка",
};

const taskStatusColor: Record<string, string> = {
  waiting_previous: "bg-gray-100 text-gray-600",
  ready: "bg-blue-100 text-blue-700",
  in_progress: "bg-amber-100 text-amber-700",
  partially_completed: "bg-orange-100 text-orange-700",
  completed: "bg-emerald-100 text-emerald-700",
  cancelled: "bg-red-100 text-red-600",
  pending: "bg-gray-100 text-gray-600",
  in_work: "bg-amber-100 text-amber-700",
  done: "bg-emerald-100 text-emerald-700",
  partially: "bg-orange-100 text-orange-700",
  blocked: "bg-red-100 text-red-600",
};

function fmtQty(value: string): string {
  const n = parseFloat(value);
  if (!Number.isFinite(n)) return "0";
  return String(Math.round(n));
}

function isTaskVisible(task: SectionBoardTask, mode: TaskBoardViewMode): boolean {
  if (mode === "active") return ["ready", "in_progress", "partially_completed", "in_work", "partially"].includes(task.status);
  if (mode === "waiting") return task.status === "waiting_previous" || task.status === "pending" || task.status === "blocked";
  return ["completed", "cancelled", "done"].includes(task.status);
}

function getTaskCellValue(task: SectionBoardTask, field: TaskSortField): string {
  switch (field) {
    case "sequence": return String(task.sequence);
    case "productSku": return task.product_sku;
    case "status": return task.status;
    case "plannedQty": return String(parseFloat(task.planned_quantity) || 0);
    case "issuedQty": return String(parseFloat(task.cache.issued_quantity) || 0);
    case "inWorkQty": return String(parseFloat(task.cache.in_work_quantity) || 0);
    case "completedQty": return String(parseFloat(task.cache.completed_quantity) || 0);
    case "transferredQty": return String(parseFloat(task.cache.transferred_quantity) || 0);
    case "rejectedQty": return String(parseFloat(task.cache.rejected_quantity) || 0);
    case "remainingQty": return String(parseFloat(task.cache.remaining_quantity) || 0);
  }
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
      className={`cursor-pointer transition-colors ${isSelected ? `${TABLE_ROW_STYLES.selectedRow}` : ""} ${isInGroup ? TABLE_ROW_STYLES.defaultGroupRow : TABLE_ROW_STYLES.defaultRow} ${isLastInGroup ? "border-b-2 border-blue-300" : "border-b"}`}
      onClick={() => {
        if (bulkMode && bulkSelection) {
          bulkSelection.selectOne(task.id);
        }
      }}
    >
      <td className="p-2">#{task.sequence}</td>
      <td className="p-2 font-medium">{task.product_sku}</td>
      <td className="p-2">
        {task.is_combined_primary && task.combined_operation_names.length > 1 ? (
          <span className="text-xs font-medium">{task.combined_operation_names.join(" + ")}</span>
        ) : (
          <span className="text-xs">{task.operation_name || "—"}</span>
        )}
      </td>
      <td className="p-2">{fmtQty(task.planned_quantity)}</td>
      <td className="p-2">{fmtQty(task.cache.issued_quantity)}</td>
      <td className="p-2">{fmtQty(task.cache.in_work_quantity)}</td>
      <td className="p-2">{fmtQty(task.cache.completed_quantity)}</td>
      <td className="p-2">{fmtQty(task.cache.rejected_quantity)}</td>
      <td className="p-2">{fmtQty(task.cache.transferred_quantity)}</td>
      <td className="p-2">{fmtQty(task.cache.remaining_quantity)}</td>
      <td className="p-2">
        <Badge variant="secondary" className={taskStatusColor[task.status] || ""}>
          {taskStatusLabels[task.status] || task.status}
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
        <Button size="sm" variant="outline" className={`${buttonBase} ${buttonDefault}`} onClick={() => handleAction("complete")} title="Завершить задачу">
          <span>Завершить</span>
        </Button>
      </td>
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
      className={`p-4 space-y-3 cursor-pointer transition-colors ${isSelected ? TABLE_ROW_STYLES.selectedMobileCard : ""} ${isLastInGroup ? "border-b-2 border-blue-300 mb-3" : "mb-0"}`}
      onClick={() => {
        if (bulkMode && bulkSelection) {
          bulkSelection.selectOne(task.id);
        }
      }}
    >
      <div className="flex items-center justify-between gap-2">
        <div className="font-semibold">
          <span className="text-muted-foreground">#{task.sequence}</span>
          <span className="ml-2 text-sm font-medium">{task.product_sku}</span>
        </div>
        <Badge variant="secondary" className={taskStatusColor[task.status] || ""}>
          {taskStatusLabels[task.status] || task.status}
        </Badge>
      </div>

      <div className="grid grid-cols-2 gap-2 text-sm">
        <div><span className="text-muted-foreground">План:</span> {fmtQty(task.planned_quantity)}</div>
        <div><span className="text-muted-foreground">Операция:</span> {task.is_combined_primary && task.combined_operation_names.length > 1 ? task.combined_operation_names.join(" + ") : (task.operation_name || "—")}</div>
        <div><span className="text-muted-foreground">Выдано:</span> {fmtQty(task.cache.issued_quantity)}</div>
        <div><span className="text-muted-foreground">В работе:</span> {fmtQty(task.cache.in_work_quantity)}</div>
        <div><span className="text-muted-foreground">Годные:</span> {fmtQty(task.cache.completed_quantity)}</div>
        <div><span className="text-muted-foreground">Брак:</span> {fmtQty(task.cache.rejected_quantity)}</div>
        <div><span className="text-muted-foreground">Передано:</span> {fmtQty(task.cache.transferred_quantity)}</div>
        <div><span className="text-muted-foreground">Остаток:</span> {fmtQty(task.cache.remaining_quantity)}</div>
      </div>

      {task.previous_stage ? (
        <div className="text-xs text-muted-foreground border-t pt-2">
          Пред. этап: годные {fmtQty(task.previous_stage.completed_quantity)}, передано {fmtQty(task.previous_stage.transferred_quantity)}
        </div>
      ) : null}

      <div className="flex gap-2 pt-1">
        <Button size="sm" variant="outline" className={`${buttonBase} ${buttonDefault}`} onClick={() => handleAction("complete")} title="Завершить задачу">
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
  const groupHasCompletable = group.tasks.some(
    (t) => !["completed", "cancelled", "done"].includes(t.status),
  );

  return (
    <tr
      className={`border-y-2 border-blue-200 cursor-pointer transition-colors font-semibold ${isBulkMode && allSelected ? TABLE_ROW_STYLES.selectedGroupHeader : TABLE_ROW_STYLES.defaultGroupHeader}`}
      onClick={isBulkMode ? onSelectGroup : undefined}
    >
      <td className="p-2">
        <div className="flex items-center gap-1.5">
          <button
            className="p-0.5 hover:bg-blue-200 rounded transition-colors"
            onClick={(e) => {
              e.stopPropagation();
              onToggleCollapse();
            }}
            title={isCollapsed ? "Раскрыть" : "Скрыть"}
          >
            {isCollapsed ? (
              <ChevronRight className="h-4 w-4 shrink-0 text-blue-600" />
            ) : (
              <ChevronDown className="h-4 w-4 shrink-0 text-blue-600" />
            )}
          </button>
          <span className="text-blue-700">#{firstTask.sequence}</span>
        </div>
      </td>
      <td className="p-2 text-blue-700">
        {firstTask.product_sku}
      </td>
      <td className="p-2 text-xs text-blue-600 font-medium">
        {firstTask.operation_name || "—"}
      </td>
      <td className="p-2 text-blue-800">{fmtQty(String(group.totalQtyPlan))}</td>
      <td className="p-2 text-blue-800">{fmtQty(String(group.tasks.reduce((s, t) => s + parseFloat(t.cache.issued_quantity), 0)))}</td>
      <td className="p-2 text-blue-800">{fmtQty(String(group.tasks.reduce((s, t) => s + parseFloat(t.cache.in_work_quantity), 0)))}</td>
      <td className="p-2 text-blue-800">{fmtQty(String(group.totalQtyDone))}</td>
      <td className="p-2 text-blue-800">{fmtQty(String(group.tasks.reduce((s, t) => s + parseFloat(t.cache.rejected_quantity), 0)))}</td>
      <td className="p-2 text-blue-800">{fmtQty(String(group.tasks.reduce((s, t) => s + parseFloat(t.cache.transferred_quantity), 0)))}</td>
      <td className="p-2 text-blue-800">{fmtQty(String(group.tasks.reduce((s, t) => s + parseFloat(t.cache.remaining_quantity), 0)))}</td>
      <td className="p-2">
        <div className="flex items-center gap-1">
          <Badge variant="secondary" className="bg-blue-200 text-blue-800 font-bold">
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
    </tr>
  );
}

// ---------------------------------------------------------------------------
// Props
// ---------------------------------------------------------------------------

type SectionTasksBoardProps = {
  tasks: SectionBoardTask[];
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
};

// ---------------------------------------------------------------------------
// Компонент
// ---------------------------------------------------------------------------

export function SectionTasksBoard({
  tasks,
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
}: SectionTasksBoardProps) {
  const [sortConfigs, setSortConfigs] = useState<SortConfig<TaskSortField>[]>([]);
  const [columnFilters, setColumnFilters] = useState<Partial<Record<TaskSortField, Set<string>>>>({});
  const [searchQuery, setSearchQuery] = useState("");

  const handleSortChange = useCallback((field: TaskSortField) => {
    setSortConfigs((prev) => nextMultiSortConfigs(prev, field));
  }, []);

  const handleColumnFilterChange = useCallback((field: TaskSortField, selected: Set<string>) => {
    setColumnFilters((prev) => ({ ...prev, [field]: selected }));
  }, []);

  const searchIndex = useMemo(() => {
    const map = new Map<string, string>();
    for (const task of tasks) {
      const terms = [
        String(task.sequence),
        task.product_sku,
        task.operation_name || "",
        task.status,
      ].filter(Boolean).map((s) => s.toLowerCase());
      map.set(String(task.id), terms.join(" "));
    }
    return map;
  }, [tasks]);

  const visibleTasks = useMemo(
    () => {
      const modeFiltered = tasks.filter((task) => isTaskVisible(task, mode));
      if (!searchQuery.trim()) return modeFiltered;
      const q = searchQuery.trim().toLowerCase();
      return modeFiltered.filter((task) => {
        const index = searchIndex.get(String(task.id));
        return index ? index.includes(q) : false;
      });
    },
    [tasks, mode, searchQuery, searchIndex],
  );

  const sortDefs: ColumnSortDef<SectionBoardTask, TaskSortField>[] = useMemo(() => [
    { field: "sequence", getSortValue: (t) => t.sequence },
    { field: "productSku", getSortValue: (t) => t.product_sku },
    { field: "status", getSortValue: (t) => t.status },
    { field: "plannedQty", getSortValue: (t) => parseFloat(t.planned_quantity) || 0 },
    { field: "issuedQty", getSortValue: (t) => parseFloat(t.cache.issued_quantity) || 0 },
    { field: "inWorkQty", getSortValue: (t) => parseFloat(t.cache.in_work_quantity) || 0 },
    { field: "completedQty", getSortValue: (t) => parseFloat(t.cache.completed_quantity) || 0 },
    { field: "transferredQty", getSortValue: (t) => parseFloat(t.cache.transferred_quantity) || 0 },
    { field: "rejectedQty", getSortValue: (t) => parseFloat(t.cache.rejected_quantity) || 0 },
    { field: "remainingQty", getSortValue: (t) => parseFloat(t.cache.remaining_quantity) || 0 },
  ], []);

  const filterPredicate = useMemo(() => {
    const hasFilters = Object.values(columnFilters).some((s) => s && s.size > 0);
    if (!hasFilters) return null;
    return (task: SectionBoardTask) => {
      for (const [field, selected] of Object.entries(columnFilters)) {
        if (selected && selected.size > 0) {
          const cellValue = getTaskCellValue(task, field as TaskSortField);
          if (!selected.has(cellValue)) return false;
        }
      }
      return true;
    };
  }, [columnFilters]);

  const uniqueValues = useMemo(() => ({
    sequence: [...new Set(visibleTasks.map((t) => String(t.sequence)))],
    productSku: [...new Set(visibleTasks.map((t) => t.product_sku))],
    status: [...new Set(visibleTasks.map((t) => t.status))],
    plannedQty: [...new Set(visibleTasks.map((t) => String(parseFloat(t.planned_quantity) || 0)))],
    issuedQty: [...new Set(visibleTasks.map((t) => String(parseFloat(t.cache.issued_quantity) || 0)))],
    inWorkQty: [...new Set(visibleTasks.map((t) => String(parseFloat(t.cache.in_work_quantity) || 0)))],
    completedQty: [...new Set(visibleTasks.map((t) => String(parseFloat(t.cache.completed_quantity) || 0)))],
    transferredQty: [...new Set(visibleTasks.map((t) => String(parseFloat(t.cache.transferred_quantity) || 0)))],
    rejectedQty: [...new Set(visibleTasks.map((t) => String(parseFloat(t.cache.rejected_quantity) || 0)))],
    remainingQty: [...new Set(visibleTasks.map((t) => String(parseFloat(t.cache.remaining_quantity) || 0)))],
  }), [visibleTasks]);

  const result = useTableQueryEngine<SectionBoardTask, TaskSortField>({
    rows: visibleTasks,
    getId: (t) => t.id,
    searchQuery: "",
    filterPredicate,
    sortConfigs,
    sortDefs,
  });

  const sortedTasks = result.rows;

  const groups = useMemo(() => {
    return groupTasksByProfile(sortedTasks, profile);
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

  const statusLabel = (status: string) => taskStatusLabels[status] || status;

  const modeCounts = useMemo(() => ({
    active: tasks.filter((t) => ["ready", "in_progress", "partially_completed", "in_work", "partially"].includes(t.status)).length,
    waiting: tasks.filter((t) => t.status === "waiting_previous" || t.status === "pending" || t.status === "blocked").length,
    completed: tasks.filter((t) => ["completed", "cancelled", "done"].includes(t.status)).length,
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
      checked: mode === "active",
      onChange: () => onModeChange("active"),
      layoutSpan: "min-w-[0px]",
    },
    {
      kind: "toggle",
      key: "mode-waiting",
      label: "Ожидают",
      badgeCount: modeCounts.waiting,
      checked: mode === "waiting",
      onChange: () => onModeChange("waiting"),
      layoutSpan: "min-w-[0px]",
    },
    {
      kind: "toggle",
      key: "mode-completed",
      label: "Завершенные",
      badgeCount: modeCounts.completed,
      checked: mode === "completed",
      onChange: () => onModeChange("completed"),
      layoutSpan: "min-w-[0px]",
    },
  ], [mode, onModeChange, searchQuery, bulkMode, onBulkModeChange, modeCounts]);

  const activeFilterSummary = useMemo(() => {
    const labels: string[] = [];
    if (searchQuery.trim()) labels.push("Поиск");
    return { count: labels.length, labels };
  }, [searchQuery]);

  return (
    <div className="space-y-3">
      <FiltersPanel
        compact
        fields={modeFields}
        onReset={() => {
          setSearchQuery("");
          bulkSelection?.clear();
          onBulkModeChange?.(false);
        }}
        hasActiveFilters={activeFilterSummary.count > 0}
        activeSummary={activeFilterSummary}
        onSelectAll={() => {
          onBulkModeChange?.(true);
          onSelectAllVisible?.(visibleTasks.map((t) => t.id));
        }}
        totalRowCount={visibleTasks.length}
      />

      {isLoading && <div className="rounded-lg border p-4 text-sm text-muted-foreground">Загрузка задач...</div>}
      {!isLoading && sortedTasks.length === 0 && (
        <div className="rounded-lg border p-4 text-sm text-muted-foreground text-center">
          {visibleTasks.length === 0 ? "Нет задач в выбранном режиме" : "Нет задач, соответствующих фильтру"}
        </div>
      )}

      {!isLoading && sortedTasks.length > 0 && (
        <>
          {/* Desktop table */}
          <div className="hidden md:block rounded-lg border overflow-auto">
            <table className="w-full border-separate border-spacing-0 text-sm">
              <thead className="[&_th]:sticky [&_th]:top-0 [&_th]:z-20 [&_th]:bg-background [&_th]:border-b">
                <tr>
                  <th className="text-left p-2">
                    <SortableFilterHeader
                      field="sequence"
                      label="Этап"
                      currentSorts={sortConfigs}
                      onSortChange={handleSortChange}
                      values={uniqueValues.sequence}
                      selectedValues={columnFilters.sequence ?? new Set()}
                      onFilterChange={handleColumnFilterChange}
                    />
                  </th>
                  <th className="text-left p-2">
                    <SortableFilterHeader
                      field="productSku"
                      label="Артикул"
                      currentSorts={sortConfigs}
                      onSortChange={handleSortChange}
                      values={uniqueValues.productSku}
                      selectedValues={columnFilters.productSku ?? new Set()}
                      onFilterChange={handleColumnFilterChange}
                    />
                  </th>
                  <th className="text-left p-2 text-xs font-medium">Операция</th>
                  <th className="text-left p-2">
                    <SortableFilterHeader
                      field="plannedQty"
                      label="План"
                      currentSorts={sortConfigs}
                      onSortChange={handleSortChange}
                      values={uniqueValues.plannedQty}
                      selectedValues={columnFilters.plannedQty ?? new Set()}
                      onFilterChange={handleColumnFilterChange}
                    />
                  </th>
                  <th className="text-left p-2">
                    <SortableFilterHeader
                      field="issuedQty"
                      label="Выдано"
                      currentSorts={sortConfigs}
                      onSortChange={handleSortChange}
                      values={uniqueValues.issuedQty}
                      selectedValues={columnFilters.issuedQty ?? new Set()}
                      onFilterChange={handleColumnFilterChange}
                    />
                  </th>
                  <th className="text-left p-2">
                    <SortableFilterHeader
                      field="inWorkQty"
                      label="В работе"
                      currentSorts={sortConfigs}
                      onSortChange={handleSortChange}
                      values={uniqueValues.inWorkQty}
                      selectedValues={columnFilters.inWorkQty ?? new Set()}
                      onFilterChange={handleColumnFilterChange}
                    />
                  </th>
                  <th className="text-left p-2">
                    <SortableFilterHeader
                      field="completedQty"
                      label="Годные"
                      currentSorts={sortConfigs}
                      onSortChange={handleSortChange}
                      values={uniqueValues.completedQty}
                      selectedValues={columnFilters.completedQty ?? new Set()}
                      onFilterChange={handleColumnFilterChange}
                    />
                  </th>
                  <th className="text-left p-2">
                    <SortableFilterHeader
                      field="rejectedQty"
                      label="Брак"
                      currentSorts={sortConfigs}
                      onSortChange={handleSortChange}
                      values={uniqueValues.rejectedQty}
                      selectedValues={columnFilters.rejectedQty ?? new Set()}
                      onFilterChange={handleColumnFilterChange}
                    />
                  </th>
                  <th className="text-left p-2">
                    <SortableFilterHeader
                      field="transferredQty"
                      label="Передано"
                      currentSorts={sortConfigs}
                      onSortChange={handleSortChange}
                      values={uniqueValues.transferredQty}
                      selectedValues={columnFilters.transferredQty ?? new Set()}
                      onFilterChange={handleColumnFilterChange}
                    />
                  </th>
                  <th className="text-left p-2">
                    <SortableFilterHeader
                      field="remainingQty"
                      label="Остаток"
                      currentSorts={sortConfigs}
                      onSortChange={handleSortChange}
                      values={uniqueValues.remainingQty}
                      selectedValues={columnFilters.remainingQty ?? new Set()}
                      onFilterChange={handleColumnFilterChange}
                    />
                  </th>
                  <th className="text-left p-2">
                    <SortableFilterHeader
                      field="status"
                      label="Статус"
                      currentSorts={sortConfigs}
                      onSortChange={handleSortChange}
                      values={uniqueValues.status}
                      selectedValues={columnFilters.status ?? new Set()}
                      onFilterChange={handleColumnFilterChange}
                      valueLabel={statusLabel}
                    />
                  </th>
                  <th className="text-left p-2 text-xs font-medium">Пред. этап</th>
                  <th className="text-left p-2 text-xs font-medium">Действия</th>
                </tr>
              </thead>
              <tbody>
                {groups.map((group) => {
                  const isCollapsed = collapsedGroups.has(group.key);
                  const isSingleTask = group.tasks.length === 1;

                  // Одна задача — рендерим напрямую без шапки группы
                  if (isSingleTask) {
                    const task = group.tasks[0];
                    const isSelected = bulkMode && bulkSelection?.isSelected(task.id);
                    return renderTaskRow(task, isSelected, bulkMode, bulkSelection, onAction, true, false);
                  }

                  return (
                    <>
                      <TableTaskGroupRow
                        key={group.key}
                        group={group}
                        isCollapsed={isCollapsed}
                        isBulkMode={!!bulkMode}
                        bulkSelection={bulkSelection}
                        onToggleCollapse={() => toggleGroup(group.key)}
                        onCompleteGroup={onCompleteGroup}
                        onSelectGroup={() => {
                          if (!bulkMode || !bulkSelection) return;
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
                        }}
                      />
                      {!isCollapsed && group.tasks.map((task, idx) => {
                        const isSelected = bulkMode && bulkSelection?.isSelected(task.id);
                        const isLast = idx === group.tasks.length - 1;
                        return renderTaskRow(task, isSelected, bulkMode, bulkSelection, onAction, isLast, true);
                      })}
                    </>
                  );
                })}
              </tbody>
            </table>
          </div>

          {/* Mobile cards */}
          <div className="md:hidden space-y-3">
            {groups.map((group) => {
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
                    className="p-3 flex items-center justify-between gap-2 border-b border-muted"
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
                        const groupHasCompletable = group.tasks.some(
                          (t) => !["completed", "cancelled", "done"].includes(t.status),
                        );
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
        </>
      )}
    </div>
  );
}
