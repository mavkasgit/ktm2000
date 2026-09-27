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
  CutLayoutCell,
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
import { useDebouncedValue } from "@/shared/lib/useDebouncedValue";
import {
  buildBoardServerQueryParams,
  isServerSortField,
  type TaskSortField,
} from "../lib/boardQueryParams";
import { groupTasksByProfile, sortGroupsByQuantityAndSize, taskGroupingDimensions } from "../lib/groupTasksByProfile";
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
import { getTaskGroupHeaderState } from "../lib/taskView";
import {
  TaskExtras,
  TaskStatusDot,
  buildTaskViewFields,
  getTaskCardClass,
  getTaskRowClass,
} from "./TaskView";
import { TABLE_ROW_STYLES } from "@/shared/lib/tableRowStyles";
import { TABLE_ROW_COMPACT } from "@/shared/lib/dataTableStyles";
import { cn } from "@/shared/utils/cn";
import { fmtQty } from "@/shared/lib/quantityFormat";
import { boardColumns } from "../lib/boardColumns";

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

function getTaskCellValue(task: SectionBoardTask, field: TaskSortField): string {
  switch (field) {
    case "sequence": return String(task.sequence);
    case "productSku": return task.product_sku;
    case "dimensions": return formatDimensionsLabel(taskGroupingDimensions(task));
    case "status": return getStatusLabel(task);
    case "plannedQty": return fmtQty(task.planned_quantity);
    case "issuedQty": return fmtQty(task.cache.issued_quantity);
    case "completedQty": return fmtQty(task.cache.completed_quantity);
    case "transferredQty": return fmtQty(task.cache.transferred_quantity);
    case "rejectedQty": return fmtQty(task.cache.rejected_quantity);
    case "remainingQty": return fmtQty(task.cache.remaining_quantity);
  }
}

// ---------------------------------------------------------------------------
// Компактная строка
// ---------------------------------------------------------------------------
// Задаётся общим правилом (CONTEXT.md, ADR-0030): доска знает только, что
// берёт общий набор, а не решает высоту строки сама.
// Кнопки задаются без size="sm": у него h-9 (36px), а min-h не уменьшает
// фиксированную высоту — именно он растягивал строку до 52px.
const ROW_CELL_CLASS = TABLE_ROW_COMPACT.cell;
const ROW_ACTION_BUTTON_CLASS = `${TABLE_ROW_COMPACT.actionButton} transition-all hover:bg-accent/50`;
const ROW_HEIGHT_PX = TABLE_ROW_COMPACT.rowHeightPx;
/** Число колонок доски: используется для полноширинных служебных строк. */
const BOARD_COLSPAN = 13;

function renderTaskRow(
  task: SectionBoardTask,
  isSelected: boolean | undefined,
  bulkMode: boolean | undefined,
  bulkSelection: BulkSelectionController | undefined,
  onAction: (type: TaskActionDialogType, task: SectionBoardTask) => void,
  onRevokeItem: ((taskId: number) => void) | undefined,
  isRevoking: boolean,
  readOnly: boolean,
  isLastInGroup = false,
  isInGroup = false,
) {
  const fields = buildTaskViewFields(task);

  const handleAction = (type: TaskActionDialogType) => {
    onAction(type, task);
  };
  return (
    <tr
      key={task.id}
      className={`cursor-pointer transition-colors ${getTaskRowClass(task, !!isSelected, isInGroup)} ${isLastInGroup ? "border-b-2 border-blue-300" : "border-b"}`}
      onClick={() => {
        if (bulkMode && bulkSelection && task.status !== "waiting_previous") {
          bulkSelection.selectOne(task.id);
        }
      }}
    >
      <td className={`${ROW_CELL_CLASS} text-center`}>
        <TaskStatusDot task={task} />
      </td>
      <td className={`${ROW_CELL_CLASS} font-medium`}>{task.product_sku}</td>
      {fields.map((field) => (
        <td key={field.key} className={cn(ROW_CELL_CLASS, field.cellClass)}>
          {field.node}
          {field.key === "operation" && (
            <TaskExtras task={task} className="block text-xs text-muted-foreground" />
          )}
        </td>
      ))}
      <td className={ROW_CELL_CLASS}>
        <Badge variant="secondary" className={cn(getStatusColor(task), TABLE_ROW_COMPACT.badge)}>
          {getStatusLabel(task)}
        </Badge>
      </td>
      <td className={ROW_CELL_CLASS}>
        {onRevokeItem ? (
          <Button
            variant={isSelected ? "default" : "outline"}
            className={ROW_ACTION_BUTTON_CLASS}
            aria-pressed={isSelected}
            disabled={isRevoking}
            onClick={(event) => {
              event.stopPropagation();
              onRevokeItem(task.id);
            }}
            title="Выбрать задание для отзыва из дневного плана"
          >
            <span>Отозвать</span>
          </Button>
        ) : readOnly ? (
          <span className="text-xs text-muted-foreground">Просмотр</span>
        ) : (
          <Button
            variant="outline"
            className={ROW_ACTION_BUTTON_CLASS}
            onClick={() => handleAction("complete")}
            disabled={!isTaskCompletable(task)}
            title={getCompletionDisabledReason(task) ?? "Завершить задачу"}
          >
            <span>Завершить</span>
          </Button>
        )}
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
  onRevokeItem: ((taskId: number) => void) | undefined,
  isRevoking: boolean,
  isLastInGroup = false,
  readOnly: boolean,
) {
  const buttonBase = `flex-1 ${TABLE_ROW_COMPACT.actionButton}`;
  const fields = buildTaskViewFields(task);
  const buttonDefault = "hover:bg-accent/50";

  const handleAction = (type: TaskActionDialogType) => {
    onAction(type, task);
  };
  return (
    <div
      key={task.id}
      className={`p-4 space-y-3 cursor-pointer transition-colors ${getTaskCardClass(task, !!isSelected)} ${isLastInGroup ? "border-b-2 border-blue-300 mb-3" : "mb-0"}`}
      onClick={() => {
        if (bulkMode && bulkSelection && task.status !== "waiting_previous") {
          bulkSelection.selectOne(task.id);
        }
      }}
    >
      <div className="flex items-center justify-between gap-2">
        <div className="flex items-center gap-2 font-semibold">
          <TaskStatusDot task={task} />
          <span className="text-sm font-medium">{task.product_sku}</span>
        </div>
        <Badge variant="secondary" className={cn(getStatusColor(task), TABLE_ROW_COMPACT.badge)}>
          {getStatusLabel(task)}
        </Badge>
      </div>

      <div className="grid grid-cols-2 gap-2 text-sm">
        {fields.map((field) => (
          <div key={field.key}>
            <span className="text-muted-foreground">{field.label}:</span> {field.node}
          </div>
        ))}
      </div>

      <TaskExtras task={task} className="block text-xs text-muted-foreground border-t pt-2" />


        {onRevokeItem ? (
          <Button
            size="sm"
            variant={isSelected ? "default" : "outline"}
            className={`${buttonBase} transition-all hover:bg-accent/50`}
            aria-pressed={isSelected}
            disabled={isRevoking}
            onClick={(event) => {
              event.stopPropagation();
              onRevokeItem(task.id);
            }}
            title="Выбрать задание для отзыва из дневного плана"
          >
            <span>Отозвать</span>
          </Button>
        ) : readOnly ? (
          <span className="text-xs text-muted-foreground">Режим просмотра</span>
        ) : (
          <Button
            size="sm"
            variant="outline"
            className={`${buttonBase} transition-all hover:bg-accent/50`}
            onClick={() => handleAction("complete")}
            disabled={!isTaskCompletable(task)}
            title={getCompletionDisabledReason(task) ?? "Завершить задачу"}
          >
            <span>Завершить</span>
          </Button>
        )}
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
  const header = getTaskGroupHeaderState(group, { isCollapsed, isBulkMode, allSelected });

  return (
    <tr
      className={`border-y border-slate-200 cursor-pointer transition-colors font-semibold ${isBulkMode && allSelected ? TABLE_ROW_STYLES.selectedGroupHeader : TABLE_ROW_STYLES.defaultGroupHeader}`}
      onClick={() => {
        if (isBulkMode) onSelectGroup();
        else onToggleCollapse();
      }}
    >
      <td className={`${ROW_CELL_CLASS} text-center`}>
        <div className="flex items-center justify-center">
          <button
            className="p-0.5 hover:bg-slate-200 rounded transition-colors text-slate-500 hover:text-slate-800"
            onClick={(e) => {
              e.stopPropagation();
              onToggleCollapse();
            }}
            title={header.collapseTitle}
          >
            {header.isCollapsed ? (
              <ChevronRight className="h-4 w-4 shrink-0" />
            ) : (
              <ChevronDown className="h-4 w-4 shrink-0" />
            )}
          </button>
        </div>
      </td>
      <td className={`${ROW_CELL_CLASS} text-slate-900`}>
        {firstTask.product_sku}
      </td>
      <td className={`${ROW_CELL_CLASS} text-xs text-slate-500 font-medium`}>
        {formatDimensionsLabel(taskGroupingDimensions(firstTask))}
      </td>
      <td className={`${ROW_CELL_CLASS} text-xs text-slate-500 font-medium`}>
        {firstTask.operation_name || "—"}
      </td>
      <td className={`${ROW_CELL_CLASS} text-slate-700`}>{fmtQty(String(group.totalQtyPlan))}</td>
      <td className={`${ROW_CELL_CLASS} text-slate-700`}>{fmtQty(String(group.tasks.reduce((s, t) => s + parseFloat(t.cache.issued_quantity), 0)))}</td>
      <td className={`${ROW_CELL_CLASS} text-slate-700`}>{fmtQty(String(group.totalQtyDone))}</td>
      <td className={`${ROW_CELL_CLASS} text-slate-700`}>{fmtQty(String(group.tasks.reduce((s, t) => s + parseFloat(t.cache.rejected_quantity), 0)))}</td>
      <td className={`${ROW_CELL_CLASS} text-slate-700`}>{fmtQty(String(group.tasks.reduce((s, t) => s + parseFloat(t.cache.transferred_quantity), 0)))}</td>
      <td className={`${ROW_CELL_CLASS} text-slate-700`}>{fmtQty(String(group.tasks.reduce((s, t) => s + parseFloat(t.cache.remaining_quantity), 0)))}</td>
      <td className={ROW_CELL_CLASS}>
        <div className="flex items-center gap-1">
          <Badge variant="secondary" className={`${TABLE_ROW_COMPACT.badge} font-bold`}>
            &times;{group.tasks.length}
          </Badge>
          {isBulkMode && header.allSelected && (
            <span className={`text-xs ${TABLE_ROW_STYLES.selectedLabel}`}>выбрано</span>
          )}
        </div>
      </td>
      <td className={`${ROW_CELL_CLASS} ${isBulkMode && allSelected ? TABLE_ROW_STYLES.selectedGroupHeader : TABLE_ROW_STYLES.defaultGroupRow}`}>
        {onCompleteGroup && (
          <Button
            variant="outline"
            className={ROW_ACTION_BUTTON_CLASS}
            onClick={(e) => {
              e.stopPropagation();
              onCompleteGroup(group);
            }}
            disabled={!header.hasCompletable}
            title={header.completeTitle}
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
  readOnly?: boolean;
  showStatusFilters?: boolean;
  showCompletedStatus?: boolean;
  bulkMode?: boolean;
  onBulkModeChange?: (enabled: boolean) => void;
  bulkSelection?: BulkSelectionController;
  profile: GroupingProfile;
  onSelectAllVisible?: (ids: number[]) => void;
  revokeSelection?: BulkSelectionController;
  onRevokeItem?: (taskId: number) => void;
  onConfirmRevoke?: () => void;
  isRevoking?: boolean;
  onCompleteGroup?: (group: TaskGroup) => void;
  page: number;
  setPage: (page: number) => void;
  limit: PageLimitOption;
  setLimit: (limit: PageLimitOption) => void;
  totalPages: number;
  rangeLabel: string;
  onServerQueryChange: (
    query: Pick<SectionBoardQueryParams, "search" | "product_sku" | "sort">,
  ) => void;
};

/**
 * Строка доски: группа, задание либо разделитель блоков («В ожидании»).
 * Разделитель — обычная `<tr>` с одной ячейкой на всю ширину, поэтому
 * табличная сетка и виртуализация (ROW_HEIGHT_PX) не ломаются.
 */
type VirtualBoardRow =
  | {
      kind: "group";
      key: string;
      /** Ключ блока (`active-…` / `waiting-…`) — по нему живёт состояние свёртки. */
      entryKey: string;
      group: TaskGroup;
      isCollapsed: boolean;
    }
  | {
      kind: "task";
      key: string;
      task: SectionBoardTask;
      isLastInGroup: boolean;
      isInGroup: boolean;
    }
  | {
      kind: "divider";
      key: string;
      /** Количество заданий в ожидании под разделителем. */
      count: number;
    };

/**
 * Порядок блоков доски: сначала активные задания, затем (если есть)
 * разделитель «В ожидании» и сами ожидающие, затем завершённые группы.
 */
type BoardEntry =
  | { kind: "group"; key: string; group: TaskGroup }
  | { kind: "divider"; key: string; count: number };

// ---------------------------------------------------------------------------
// Компонент
export function SectionTasksBoard({
  tasks,
  total,
  isLoading,
  mode,
  onModeChange,
  onAction,
  readOnly = false,
  showStatusFilters = true,
  showCompletedStatus = false,
  bulkMode,
  onBulkModeChange,
  bulkSelection,
  profile,
  onSelectAllVisible,
  revokeSelection,
  onRevokeItem,
  onConfirmRevoke,
  isRevoking = false,
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
  const debouncedSearch = useDebouncedValue(searchQuery);
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

  // Поиск колонки по полю для клиентской сортировки: таблица статична.
  const sortDefsByField = useMemo(
    () =>
      Object.fromEntries(sortDefs.map((def) => [def.field, def])) as Record<
        TaskSortField,
        ColumnSortDef<SectionBoardTask, TaskSortField> | undefined
      >,
    [sortDefs],
  );

  const uniqueValues = useMemo(() => ({
    sequence: [...new Set(visibleTasks.map((t) => String(t.sequence)))],
    productSku: [...new Set(visibleTasks.map((t) => t.product_sku))],
    dimensions: [...new Set(visibleTasks.map((t) => JSON.stringify(taskGroupingDimensions(t) ?? null)))].sort(
      (a, b) => formatDimensionsFilterValue(a).localeCompare(formatDimensionsFilterValue(b), "ru"),
    ),
    status: [...new Set(visibleTasks.map((t) => getStatusLabel(t)))],
    plannedQty: [...new Set(visibleTasks.map((t) => fmtQty(t.planned_quantity)))],
    issuedQty: [...new Set(visibleTasks.map((t) => fmtQty(t.cache.issued_quantity)))],
    completedQty: [...new Set(visibleTasks.map((t) => fmtQty(t.cache.completed_quantity)))],
    transferredQty: [...new Set(visibleTasks.map((t) => fmtQty(t.cache.transferred_quantity)))],
    rejectedQty: [...new Set(visibleTasks.map((t) => fmtQty(t.cache.rejected_quantity)))],
    remainingQty: [...new Set(visibleTasks.map((t) => fmtQty(t.cache.remaining_quantity)))],
  }), [visibleTasks]);

  // Порядок строк доски. Колонки серверной сортировки (sequence/productSku/
  // status/dimensions) уже пришли в нужном порядке с сервера, остальные
  // клиент упорядочивает здесь, поверх ответа и до группировки. Без сортировки
  // действует дефолт «количество убыв., размер убыв.», а внутри группы —
  // «статус, затем sequence» (CONTEXT.md, раздел «Сортировка строк по размеру»).
  const hasActiveSort = sortConfigs.length > 0;
  const clientSortConfigs = useMemo(
    () => sortConfigs.filter((config) => !isServerSortField(config.field)),
    [sortConfigs],
  );
  const sortedTasks = useMemo(() => {
    // Приоритеты сравниваются по очереди, от старшего к младшему: сортировка
    // устойчива, поэтому при равенстве по клиентским колонкам сохраняется
    // порядок сервера (за серверные колонки отвечает он).
    const clientSorts = clientSortConfigs.flatMap((config) => {
      const def = sortDefsByField[config.field];
      return def ? [{ def, order: config.order }] : [];
    });
    if (clientSorts.length === 0) return visibleTasks;
    return [...visibleTasks].sort((a, b) => {
      for (const { def, order } of clientSorts) {
        const left = def.getSortValue(a);
        const right = def.getSortValue(b);
        if (left === right) continue;
        const cmp = left < right ? -1 : 1;
        return order === "asc" ? cmp : -cmp;
      }
      return 0;
    });
  }, [visibleTasks, clientSortConfigs, sortDefsByField]);

  const groups = useMemo(() => {
    // groupTasksByProfile сохраняет порядок первого появления, поэтому
    // сортировка (серверная или клиентская) доходит до строк таблицы.
    const grouped = groupTasksByProfile(sortedTasks, profile);
    if (hasActiveSort) return grouped;

    const ordered = sortGroupsByQuantityAndSize(grouped);
    for (const g of ordered) {
      g.tasks.sort((a, b) => {
        const pA = getStatusPriority(a);
        const pB = getStatusPriority(b);
        if (pA !== pB) return pA - pB;
        return a.sequence - b.sequence;
      });
    }

    return ordered;
  }, [sortedTasks, profile, hasActiveSort]);

  // Порядок доски: активные задания → разделитель «В ожидании» → ожидающие →
  // завершённые группы. Сортировка и группировка по профилю внутри каждого
  // блока сохраняются: берём те же группы и те же строки, только разрезаем
  // смешанные группы по категории задания.
  const boardEntries = useMemo((): BoardEntry[] => {
    const activeGroups: TaskGroup[] = [];
    const waitingGroups: TaskGroup[] = [];
    const completedGroups: TaskGroup[] = [];

    for (const g of groups) {
      if (g.tasks.every((t) => getStatusPriority(t) >= 2)) {
        completedGroups.push(g);
        continue;
      }
      const activeTasks = g.tasks.filter((t) => getStatusPriority(t) === 0);
      const waitingTasks = g.tasks.filter((t) => getStatusPriority(t) === 1);
      if (activeTasks.length > 0) activeGroups.push({ ...g, tasks: activeTasks });
      if (waitingTasks.length > 0) waitingGroups.push({ ...g, tasks: waitingTasks });
    }

    const entries: BoardEntry[] = [];
    activeGroups.forEach((g, i) => entries.push({ kind: "group", key: `active-${i}-${g.key}`, group: g }));
    if (waitingGroups.length > 0) {
      const waitingCount = waitingGroups.reduce((sum, g) => sum + g.tasks.length, 0);
      entries.push({ kind: "divider", key: "divider-waiting", count: waitingCount });
      waitingGroups.forEach((g, i) => entries.push({ kind: "group", key: `waiting-${i}-${g.key}`, group: g }));
    }
    completedGroups.forEach((g, i) => entries.push({ kind: "group", key: `completed-${i}-${g.key}`, group: g }));
    return entries;
  }, [groups]);

  // Задания, доступные для группового выбора: ожидающие в выделение не попадают.
  const selectableTaskIds = useMemo(
    () => visibleTasks.filter((t) => getTaskViewCategory(t) !== "waiting").map((t) => t.id),
    [visibleTasks],
  );

  // Группы по умолчанию свёрнуты; пользователь может раскрыть любую вручную.
  // Сохраняем развёрнутые пользователем ключи, остальные — свернуты.
  const [manuallyExpanded, setManuallyExpanded] = useState<Set<string>>(new Set());
  const collapsedGroups = useMemo(() => {
    const collapsed = new Set<string>();
    for (const entry of boardEntries) {
      if (entry.kind !== "group") continue;
      if (entry.group.tasks.length > 1 && !manuallyExpanded.has(entry.key)) {
        collapsed.add(entry.key);
      }
    }
    return collapsed;
  }, [boardEntries, manuallyExpanded]);

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

  const modeFields = useMemo((): FiltersPanelField[] => {
    const fields: FiltersPanelField[] = [
      {
        kind: "search",
        key: "search",
        value: searchQuery,
        onChange: setSearchQuery,
        placeholder: "Поиск",
        layoutSpan: "min-w-[250px]",
      },
      ...(readOnly ? [] : [{
        kind: "bulk" as const,
        key: "bulk-mode",
        enabled: bulkMode ?? false,
        onChange: (enabled: boolean) => onBulkModeChange?.(enabled),
      }]),
    ];
    if (showStatusFilters) {
      fields.push(
        {
          kind: "toggle",
          key: "mode-active",
          label: "Активные",
          badgeCount: modeCounts.active,
          checked: mode.active,
          onChange: () => onModeChange({ ...mode, active: !mode.active }),
          hideIcon: true,
          layoutSpan: "min-w-[0px]",
        },
        {
          kind: "toggle",
          key: "mode-waiting",
          label: "Ожидают",
          badgeCount: modeCounts.waiting,
          checked: mode.waiting,
          onChange: () => onModeChange({ ...mode, waiting: !mode.waiting }),
          hideIcon: true,
          tone: "amber",
          layoutSpan: "min-w-[0px]",
        },
      );
      if (showCompletedStatus) {
        fields.push({
          kind: "toggle",
          key: "mode-completed",
          label: "Завершенные",
          badgeCount: modeCounts.completed,
          checked: mode.completed,
          onChange: () => onModeChange({ ...mode, completed: !mode.completed }),
          hideIcon: true,
          layoutSpan: "min-w-[0px]",
        });
      }
    }
    return fields;
  }, [mode, onModeChange, searchQuery, bulkMode, onBulkModeChange, modeCounts, readOnly, showCompletedStatus, showStatusFilters]);

  const handleResetAllFilters = useCallback(() => {
    setSearchQuery("");
    resetAllFilters();
    bulkSelection?.clear();
    onBulkModeChange?.(false);
    setPage(1);
  }, [resetAllFilters, bulkSelection, onBulkModeChange, setPage]);

  const virtualRows = useMemo((): VirtualBoardRow[] => {
    const items: VirtualBoardRow[] = [];
    for (const entry of boardEntries) {
      if (entry.kind === "divider") {
        items.push({ kind: "divider", key: entry.key, count: entry.count });
        continue;
      }
      const group = entry.group;
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

      const isCollapsed = collapsedGroups.has(entry.key);
      items.push({
        kind: "group",
        key: `group-${entry.key}`,
        entryKey: entry.key,
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
  }, [boardEntries, collapsedGroups]);

  /** Разделитель блоков «В ожидании»: строка таблицы на всю ширину. */
  const renderWaitingDivider = useCallback((row: Extract<VirtualBoardRow, { kind: "divider" }>) => (
    <tr key={row.key} data-testid="waiting-divider">
      <td colSpan={BOARD_COLSPAN} className="p-0" style={{ height: ROW_HEIGHT_PX }}>
        <div className="flex h-10 items-center gap-2 border-y border-amber-200 bg-amber-50/70 px-2">
          <span className="text-[11px] font-semibold uppercase tracking-wide text-amber-800">
            В ожидании
          </span>
          <span className="text-[11px] tabular-nums text-amber-800/70">{row.count}</span>
          <span className="h-px flex-1 bg-amber-200" />
        </div>
      </td>
    </tr>
  ), []);

  /** Заголовок блока «В ожидании» для мобильных карточек. */
  const renderWaitingDividerMobile = useCallback((key: string, count: number) => (
    <div key={key} className="flex items-center gap-2 px-1">
      <span className="text-[11px] font-semibold uppercase tracking-wide text-amber-800">
        В ожидании
      </span>
      <span className="text-[11px] tabular-nums text-amber-800/70">{count}</span>
      <span className="h-px flex-1 bg-amber-200" />
    </div>
  ), []);

  const renderVirtualRow = useCallback(
    (row: VirtualBoardRow) => {
      if (row.kind === "divider") return renderWaitingDivider(row);
      if (row.kind === "group") {
        return (
          <TableTaskGroupRow
            key={row.key}
            group={row.group}
            isCollapsed={row.isCollapsed}
            isBulkMode={!!bulkMode}
            bulkSelection={bulkSelection}
            onToggleCollapse={() => toggleGroup(row.entryKey)}
            onCompleteGroup={readOnly ? undefined : onCompleteGroup}
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

      const isSelected = revokeSelection
        ? revokeSelection.isSelected(row.task.id)
        : bulkMode && bulkSelection?.isSelected(row.task.id);
      return renderTaskRow(
        row.task,
        isSelected,
        bulkMode,
        bulkSelection,
        onAction,
        onRevokeItem,
        isRevoking,
        readOnly,
        row.isLastInGroup,
        row.isInGroup,
      );
    },
    [bulkMode, bulkSelection, onAction, onCompleteGroup, onRevokeItem, readOnly, renderWaitingDivider, revokeSelection, toggleGroup],
  );

  const headerCellClass = cn(
    DATA_TABLE_STYLES.headerRow,
    DATA_TABLE_STYLES.headerCell,
    TABLE_ROW_COMPACT.headerCell,
  );

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
        onSelectAll={onSelectAllVisible ? () => {
          onBulkModeChange?.(true);
          onSelectAllVisible(selectableTaskIds);
        } : undefined}
        totalRowCount={selectableTaskIds.length}
        actions={
          revokeSelection && revokeSelection.selectedCount > 0 ? (
            <div className="flex items-center gap-2">
              <span className="text-xs text-slate-600">
                Выбрано для отзыва: {revokeSelection.selectedCount}
              </span>
              <Button
                size="sm"
                onClick={onConfirmRevoke}
                disabled={!onConfirmRevoke || isRevoking}
              >
                {isRevoking ? "Отзыв…" : "Подтвердить отзыв"}
              </Button>
            </div>
          ) : null
        }
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
                  {boardColumns.map((column) => (
                    <th
                      key={column.id}
                      className={`${headerCellClass} ${column.className ?? "text-left"}`}
                    >
                      {column.filterField ? (
                        <SortableFilterHeader
                          field={column.filterField}
                          label={column.label}
                          currentSorts={sortConfigs}
                          onSortChange={handleSortChange}
                          sortable={Boolean(column.sortField)}
                          values={uniqueValues[column.filterField] ?? []}
                          {...bindColumn(column.filterField)}
                          valueLabel={column.valueLabel}
                        />
                      ) : (
                        <span className="text-xs font-medium text-muted-foreground">
                          {column.label}
                        </span>
                      )}
                    </th>
                  ))}
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
                    <td colSpan={BOARD_COLSPAN} className="p-8 text-center text-sm text-muted-foreground">
                      Нет задач, соответствующих фильтру
                    </td>
                  </tr>
                </tbody>
              ) : (
                <VirtualizedTableBody
                  rows={virtualRows}
                  rowHeight={ROW_HEIGHT_PX}
                  colSpan={BOARD_COLSPAN}
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
            ) : boardEntries.map((entry) => {
              if (entry.kind === "divider") return renderWaitingDividerMobile(entry.key, entry.count);
              const group = entry.group;
              const isCollapsed = collapsedGroups.has(entry.key);
              const isSingleTask = group.tasks.length === 1;

              // Одна задача — рендерим напрямую без шапки группы
              if (isSingleTask) {
                const task = group.tasks[0];
                const isSelected = revokeSelection
                  ? revokeSelection.isSelected(task.id)
                  : bulkMode && bulkSelection?.isSelected(task.id);
                return renderMobileCard(task, isSelected, bulkMode, bulkSelection, onAction, onRevokeItem, isRevoking, true, readOnly);
              }

              const mobileHeader = getTaskGroupHeaderState(group, {
                isCollapsed,
                isBulkMode: Boolean(bulkMode),
                allSelected: Boolean(bulkMode && bulkSelection?.isAllSelected(group.tasks.map((t) => t.id))),
              });
              return (
                <div key={entry.key} className={`rounded-lg overflow-hidden transition-colors ${bulkMode && bulkSelection?.isAllSelected(group.tasks.map(t => t.id)) ? TABLE_ROW_STYLES.selectedGroupContainer : TABLE_ROW_STYLES.defaultGroupContainer}`}>
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
                        toggleGroup(entry.key);
                      }
                    }}
                  >
                    <div className="flex items-center gap-2 min-w-0">
                      <button
                        className="p-0.5 hover:bg-muted/50 rounded transition-colors cursor-pointer"
                        onClick={(e) => {
                          e.stopPropagation();
                          toggleGroup(entry.key);
                        }}
                        title={mobileHeader.collapseTitle}
                      >
                        {mobileHeader.isCollapsed ? (
                          <ChevronRight className="h-4 w-4 text-muted-foreground" />
                        ) : (
                          <ChevronDown className="h-4 w-4 text-muted-foreground" />
                        )}
                      </button>
                      <span className="font-semibold text-sm truncate">
                        {group.label}
                      </span>
                      {bulkMode && mobileHeader.allSelected && (
                        <span className={`text-xs ${TABLE_ROW_STYLES.selectedLabel} ml-1`}>выбрано</span>
                      )}
                    </div>
                    <div className="flex items-center gap-2 shrink-0">
                      <Badge variant="secondary" className={`bg-blue-100 text-blue-700 ${TABLE_ROW_COMPACT.badge}`}>
                        &times;{group.tasks.length}
                      </Badge>
                      {onCompleteGroup && !readOnly && (
                        <Button
                          variant="outline"
                          className={ROW_ACTION_BUTTON_CLASS}
                          onClick={(e) => {
                            e.stopPropagation();
                            onCompleteGroup(group);
                          }}
                          disabled={!mobileHeader.hasCompletable}
                          title={mobileHeader.completeTitle}
                        >
                          <span>Завершить группу</span>
                        </Button>
                      )}
                    </div>
                  </div>
                  {!isCollapsed && <div className="divide-y divide-muted">{group.tasks.map((task, idx) => {
                    const isLast = idx === group.tasks.length - 1;
                    const isSelected = revokeSelection
                      ? revokeSelection.isSelected(task.id)
                      : bulkMode && bulkSelection?.isSelected(task.id);
                    return renderMobileCard(task, isSelected, bulkMode, bulkSelection, onAction, onRevokeItem, isRevoking, isLast, readOnly);
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
