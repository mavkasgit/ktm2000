/**
 * components/SectionTasksBoard.tsx
 * =================================
 * Доска задач одного участка производства.
 *
 * Сохраняет весь старый функционал (режимы, bulk, действия) +
 * использует новый groupTasksByProfile вместо BoardRowItem.
 */

import { useMemo, useState, useCallback, useEffect, useRef, type ReactNode } from "react";
import { ChevronDown, ChevronRight } from "lucide-react";
import type { SectionBoardQueryParams, SectionBoardTask, TaskGroup } from "@/shared/api/shopfloor";
import { formatDimensionsFilterValue, formatDimensionsLabel } from "@/shared/api/stock";
import {
  Badge,
  ActionWithReason,
  Button,
  CutLayoutCell,
  DataTableColumnHeader,
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
import { getAriaSort } from "@/shared/lib/multiSort";
import { isFirstRowsLoad } from "@/shared/lib/tableQueryPlaceholder";
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
  getCompletionBlockReason,
  getTaskViewCategory,
  isTaskFullyTransferred,
} from "../lib/taskStatus";
import {
  applyGroupField,
  EMPTY_DRAFT_QTY,
  groupDraftValue as groupDraftValueOf,
  recordedFact,
  resolveGroupFact,
  draftQtyFor,
  isTransformTask,
  taskFactCeiling,
  withDraftField,
  type BulkDraft,
  type DraftField,
  type DraftQty,
} from "../lib/bulkDraft";
import { DraftQtyInput } from "./DraftQtyInput";
import {
  getTaskGroupHeaderState,
  packagingBreakdownLabel,
  taskOperations,
} from "../lib/taskView";
import {
  TaskStatusDot,
  buildTaskViewFields,
  getTaskCardClass,
  getTaskGroupRailClass,
  getTaskRowClass,
  getTaskStripeClass,
} from "./TaskView";
import { TABLE_ROW_STYLES } from "@/shared/lib/tableRowStyles";
import { TABLE_ROW_COMPACT, TABLE_ROW_DENSE } from "@/shared/lib/dataTableStyles";
import { actionReasonText } from "@/shared/lib/actionReasons";
import { factPortion, resolveFactQuantity } from "../lib/factQuantity";
import { cn } from "@/shared/utils/cn";
import { fmtQty, toQtyInteger } from "@/shared/lib/quantityFormat";
import { boardColumns, visibleBoardColumns } from "../lib/boardColumns";

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

/**
 * Колонки, которые доска фильтрует сама, по уже пришедшим строкам. Список
 * берётся из описания (`clientOnly`): ручной перечень расходился с шапкой —
 * колонку переименовали в описании, а здесь забыли, и фильтр уходил на
 * сервер, который о нём не знает.
 */
const CLIENT_FILTER_FIELDS: TaskSortField[] = boardColumns.flatMap((column) =>
  column.clientOnly && column.filterField ? [column.filterField] : [],
);

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
// Плотность 32px — общий уточнённый набор (ADR-0033), не местная выдумка:
// с такой же высотой идут «Передачи» и «Остатки».
// Кнопки задаются без size="sm": у него h-9 (36px), а min-h не уменьшает
// фиксированную высоту — именно он растягивал строку до 52px.
const ROW_ACTION_BUTTON_CLASS = `${TABLE_ROW_DENSE.actionButton} transition-all hover:bg-accent/50`;
const ROW_BADGE_CLASS = TABLE_ROW_DENSE.badge;
const ROW_HEIGHT_PX = TABLE_ROW_DENSE.rowHeightPx;

/**
 * Ячейка строки доски. Вертикальный отступ — ноль, а не 4px общего набора:
 * самое высокое содержимое строки — кнопка действия 24px, и с отступом 4+4px
 * это давало 32px контента; с границей ячейки (1px, у последней строки блока
 * 3px) строка вырастала до 33/35px, а виртуализация считает её 32px
 * (`ROW_HEIGHT_PX`) и разъезжалась с раскладкой. Строка обязана быть ровно
 * 32px, поэтому отступ убран, а содержимое центрируется `align-middle`.
 * Уточнение объявлено рядом с доской и развёрнуто поверх общего набора
 * (ADR-0030).
 */
const ROW_CELL_CLASS = cn(TABLE_ROW_DENSE.cell, "py-0 align-middle");

/**
 * Ячейка черновика у выделенной строки: «Годные» и «Брак» становятся полями
 * ввода (#283). Потолок — доступное на задачу; введённое сверх него помечается
 * без наведения: в плотной строке — знаком, в карточке — словом.
 */
function renderDraftCell(
  task: SectionBoardTask,
  cell: "completed" | "rejected",
  draft: RowDraftContext,
  variant: "row" | "card",
) {
  const field: DraftField = cell === "completed" ? "good" : "defect";
  const recorded = cell === "completed" ? task.cache.completed_quantity : task.cache.rejected_quantity;
  // У раскроя факт вводится в заготовках входа (ADR-0002, ADR-0064), поэтому
  // подпись поля называет именно их: «Годные» для пилы — выходные штуки другой
  // размерности, и одинаковое имя читалось бы как обещание записать выходы.
  const transform = isTransformTask(task);
  const label = cell === "completed"
    ? transform
      ? "раскроено заготовок"
      : "годные"
    : transform
      ? "брак заготовок"
      : "брак";
  const overPlan = draft.overPlan[field];
  return (
    <span className={variant === "card" ? "flex flex-col items-start gap-0.5" : "flex items-center gap-1"}>
      <DraftQtyInput
        value={draft.value[field]}
        onChange={(next) => draft.onChange(field, next)}
        recorded={fmtQty(recorded)}
        ariaLabel={`${task.product_sku}: ${label}`}
        issueText={draft.issue[field]}
        overPlan={overPlan}
      />
      {overPlan &&
        (variant === "card" ? (
          <span className="text-[11px] font-medium leading-none text-amber-700">
            сверх плана: доступно {fmtQty(taskFactCeiling(task))} шт.
          </span>
        ) : (
          <span
            aria-hidden
            className="text-[10px] leading-none text-amber-600"
            title={`Сверх плана: доступно на задачу ${fmtQty(taskFactCeiling(task))} шт.`}
          >
            ▲
          </span>
        ))}
    </span>
  );
}

/**
 * Контекст массового ввода для строки или карточки. `undefined` — строка не
 * выделена, и ячейки показывают записанный факт как обычно: клиентские фильтр
 * и сортировка по этим колонкам продолжают работать по записанной величине, а
 * черновик их не двигает (#283, п. 1).
 */
/**
 * Убирает набранное в поле группы из состояния: поле снова выводится из строк.
 */
function forgetGroupInput(
  inputs: Record<string, DraftQty>,
  groupKey: string,
): Record<string, DraftQty> {
  if (!(groupKey in inputs)) return inputs;
  const next = { ...inputs };
  delete next[groupKey];
  return next;
}

type RowDraftContext = {
  value: DraftQty;
  overPlan: { good: boolean; defect: boolean };
  /** Причина домена по колонке: ввод верен синтаксически, но неприменим. */
  issue: { good: string | null; defect: string | null };
  onChange: (field: DraftField, value: string) => void;
};

/**
 * Причина, по которой ввод колонки не применяется, — текст у поля. Синтаксис
 * проверяет поле (`normalizeQuantityInput`), а «факт меньше записанного» —
 * домен: бэкенд принимает порцию и отрицательных количеств не знает.
 */
function draftFieldIssue(task: SectionBoardTask, value: string, field: DraftField): string | null {
  const resolution = resolveFactQuantity(value, recordedFact(task, field));
  return resolution.kind === "invalid" ? actionReasonText(resolution.reason) : null;
}

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
  hasPackaging?: boolean,
  draft?: RowDraftContext,
) {
  const fields = buildTaskViewFields(task, hasPackaging);
  const blockReason = getCompletionBlockReason(task);
  // Рёбра блока живут на ячейках, а не на `<tr>`: таблица объявлена
  // `border-separate`, и границы строк браузер в ней не рисует вовсе (проверено
  // пиксельно) — `border-b` на `<tr>` был невидим, как и прежняя граница
  // `border-b-2 border-blue-300`. Одиночные строки (не группа) остаются без
  // линий, как и были.
  const edgeClass = isInGroup
    ? isLastInGroup
      ? TABLE_ROW_STYLES.groupBlockBoundary
      : TABLE_ROW_STYLES.groupChildSeparator
    : "";
  const cellClass = edgeClass ? cn(ROW_CELL_CLASS, edgeClass) : ROW_CELL_CLASS;

  const handleAction = (type: TaskActionDialogType) => {
    onAction(type, task);
  };
  return (
    <tr
      data-row-kind="board-task"
      // id задачи — адрес строки для e2e массового ввода (#283): строки одного
      // артикула неразличимы по тексту.
      data-task-id={task.id}
      key={task.id}
      // Высота задана явно: в readOnly («План») кнопки в строке нет, и без
      // этого строка схлопнулась бы до высоты текста (30px против 32px).
      style={{ height: ROW_HEIGHT_PX }}
      // Клавиатурная модель массового ввода (#283): Tab по строкам, Enter или
      // пробел — тумблер выделения, со выделенной строки Tab уходит в её поля.
      // Сетки (grid) здесь нет намеренно: строки виртуализированы, и «Tab по
      // отрисованным» — единственная честная модель.
      tabIndex={bulkMode ? 0 : undefined}
      aria-selected={bulkMode ? Boolean(isSelected) : undefined}
      className={`cursor-pointer transition-colors ${getTaskRowClass(task, !!isSelected, isInGroup)}`}
      onClick={() => {
        if (bulkMode && bulkSelection && task.status !== "waiting_previous") {
          bulkSelection.selectOne(task.id);
        }
      }}
      onKeyDown={(event) => {
        if (!bulkMode || !bulkSelection) return;
        // Клавиши строки не перехватывают то, что нажато в её кнопке или поле:
        // Enter на кнопке «Завершить» обязан открыть диалог, а не переключить
        // выделение.
        if (event.target !== event.currentTarget) return;
        if (event.key !== "Enter" && event.key !== " ") return;
        event.preventDefault();
        if (task.status !== "waiting_previous") bulkSelection.selectOne(task.id);
      }}
    >
      <td className={cn(cellClass, getTaskStripeClass(task), "relative text-center")}>
        {/* Направляющая блока: строка связана с шевроном группы и с соседями.
            У последней строки она обрывается на своей точке — блок имеет конец,
            а не продолжается в следующую группу. */}
        {isInGroup && (
          <span
            aria-hidden
            className={cn(
              "pointer-events-none absolute left-1/2 w-0.5 -translate-x-1/2",
              TABLE_ROW_STYLES.groupConnector,
              isLastInGroup ? "top-0 h-1/2" : "inset-y-0",
            )}
          />
        )}
        <span className="relative z-10 inline-flex">
          <TaskStatusDot task={task} />
        </span>
      </td>
      <td className={cn(cellClass, "font-medium")}>{task.product_sku}</td>
      {fields.map((field) => (
        <td key={field.key} className={cn(cellClass, field.cellClass)}>
          {draft && (field.key === "completed" || field.key === "rejected")
            ? renderDraftCell(task, field.key, draft, "row")
            : field.node}
        </td>
      ))}
      <td className={cellClass}>
        <Badge variant="secondary" className={cn(getStatusColor(task), ROW_BADGE_CLASS)}>
          {getStatusLabel(task)}
        </Badge>
      </td>
      <td className={cellClass}>
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
          <ActionWithReason reason={blockReason}>
            <Button
              variant="outline"
              className={ROW_ACTION_BUTTON_CLASS}
              onClick={() => handleAction("complete")}
              disabled={blockReason !== null}
              title={blockReason ? actionReasonText(blockReason) : "Завершить задачу"}
            >
              <span>Завершить</span>
            </Button>
          </ActionWithReason>
        )}
      </td>
      <TableCornerResetCell className={edgeClass || undefined} />
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
  hasPackaging?: boolean,
  draft?: RowDraftContext,
) {
  const buttonBase = `flex-1 ${TABLE_ROW_COMPACT.actionButton}`;
  const fields = buildTaskViewFields(task, hasPackaging);
  const blockReason = getCompletionBlockReason(task);
  const buttonDefault = "hover:bg-accent/50";

  const handleAction = (type: TaskActionDialogType) => {
    onAction(type, task);
  };
  return (
    <div
      key={task.id}
      data-task-id={task.id}
      tabIndex={bulkMode ? 0 : undefined}
      className={`p-4 space-y-3 cursor-pointer transition-colors ${getTaskCardClass(task, !!isSelected)} ${isLastInGroup ? "border-b-2 border-blue-300 mb-3" : "mb-0"}`}
      onClick={() => {
        if (bulkMode && bulkSelection && task.status !== "waiting_previous") {
          bulkSelection.selectOne(task.id);
        }
      }}
      onKeyDown={(event) => {
        if (!bulkMode || !bulkSelection) return;
        // Клавиши строки не перехватывают то, что нажато в её кнопке или поле:
        // Enter на кнопке «Завершить» обязан открыть диалог, а не переключить
        // выделение.
        if (event.target !== event.currentTarget) return;
        if (event.key !== "Enter" && event.key !== " ") return;
        event.preventDefault();
        if (task.status !== "waiting_previous") bulkSelection.selectOne(task.id);
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
            <span className="text-muted-foreground">{field.label}:</span>{" "}
            {draft && (field.key === "completed" || field.key === "rejected")
              ? renderDraftCell(task, field.key, draft, "card")
              : field.node}
          </div>
        ))}
      </div>

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
          <ActionWithReason reason={blockReason} layout="column">
            <Button
              size="sm"
              variant="outline"
              className={`${buttonBase} transition-all hover:bg-accent/50`}
              onClick={() => handleAction("complete")}
              disabled={blockReason !== null}
              title={blockReason ? actionReasonText(blockReason) : "Завершить задачу"}
            >
              <span>Завершить</span>
            </Button>
          </ActionWithReason>
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
  hasPackaging,
  groupQty,
  groupIssue,
  groupOverPlan,
  onGroupQtyChange,
}: {
  group: TaskGroup;
  isCollapsed: boolean;
  isBulkMode: boolean;
  bulkSelection?: BulkSelectionController;
  onToggleCollapse: () => void;
  onSelectGroup: () => void;
  /** Участок без упаковочных операций — ячейки «Упаковка» в шапке группы нет. */
  hasPackaging?: boolean;
  /**
   * Групповой ввод (#283): в массовом режиме ячейки «Годные»/«Брак» шапки —
   * поля, и введённое раскладывается по строкам группы. Сумм в шапке тогда нет:
   * их место занял инпут, а итог «к записи» показывает футер.
   */
  groupQty?: DraftQty;
  /** Причина домена по колонке: «факт меньше записанного» и подобное. */
  groupIssue?: { good: string | null; defect: string | null };
  groupOverPlan?: { good: boolean; defect: boolean };
  onGroupQtyChange?: (field: DraftField, value: string) => void;
}) {
  const taskIds = group.tasks.map((t) => t.id);
  const allSelected = bulkSelection?.isAllSelected(taskIds) ?? false;
  const firstTask = group.tasks[0];
  const header = getTaskGroupHeaderState(group, { isCollapsed, isBulkMode, allSelected });
  const groupInput = Boolean(isBulkMode && onGroupQtyChange);
  const recordedGood = group.tasks.reduce((sum, task) => sum + parseFloat(task.cache.completed_quantity), 0);
  const recordedDefect = group.tasks.reduce((sum, task) => sum + parseFloat(task.cache.rejected_quantity), 0);
  const overPlan = groupOverPlan ?? { good: false, defect: false };
  // Рёбра блока — на ячейках: границы `<tr>` в таблице доски (`border-separate`)
  // браузер не рисует, и `border-y` на строке был невидим.
  const headerCellClass = cn(ROW_CELL_CLASS, TABLE_ROW_STYLES.groupHeaderCell);
  const railClass = getTaskGroupRailClass(group.tasks);

  return (
    <tr
      style={{ height: ROW_HEIGHT_PX }}
      tabIndex={isBulkMode ? 0 : undefined}
      aria-selected={isBulkMode ? allSelected : undefined}
      className={`cursor-pointer transition-colors font-semibold ${isBulkMode && allSelected ? TABLE_ROW_STYLES.selectedGroupHeader : TABLE_ROW_STYLES.defaultGroupHeader}`}
      onClick={() => {
        if (isBulkMode) onSelectGroup();
        else onToggleCollapse();
      }}
      onKeyDown={(event) => {
        if (!isBulkMode) return;
        if (event.target !== event.currentTarget) return;
        if (event.key !== "Enter" && event.key !== " ") return;
        event.preventDefault();
        onSelectGroup();
      }}
    >
      <td className={cn(headerCellClass, railClass, "relative text-center")}>
        {/* Спуск от шеврона к строкам: без него направляющая блока начинается
            ниоткуда и читается как случайная линия. У свёрнутой группы строк
            нет — нет и спуска. */}
        {!isCollapsed && (
          <span
            aria-hidden
            className={cn(
              "pointer-events-none absolute bottom-0 left-1/2 h-2 w-0.5 -translate-x-1/2",
              TABLE_ROW_STYLES.groupConnector,
            )}
          />
        )}
        <div className="relative z-10 flex items-center justify-center">
          <button
            className="p-0.5 hover:bg-slate-200 rounded transition-colors text-slate-500 hover:text-slate-800 dark:text-slate-400 dark:hover:bg-slate-700 dark:hover:text-slate-100"
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
      <td className={`${headerCellClass} text-slate-900 dark:text-slate-100`}>
        {firstTask.product_sku}
      </td>
      <td className={`${headerCellClass} text-xs text-slate-500 font-medium dark:text-slate-400`}>
        {formatDimensionsLabel(taskGroupingDimensions(firstTask))}
      </td>
      <td className={`${headerCellClass} text-xs text-slate-500 font-medium dark:text-slate-400`}>
        {firstTask.transforms_dimensions ? (
          <CutLayoutCell
            layout={firstTask.cut_layout}
            fallback={formatDimensionsLabel(taskGroupingDimensions(firstTask))}
          />
        ) : (
          taskOperations(firstTask).join(" · ") || "—"
        )}
      </td>
      {hasPackaging !== false && (
        <td className={`${headerCellClass} text-xs text-slate-500 font-medium dark:text-slate-400`}>
          {packagingBreakdownLabel(group.tasks, fmtQty)}
        </td>
      )}
      <td className={`${headerCellClass} text-slate-700 dark:text-slate-200`}>{fmtQty(String(group.totalQtyPlan))}</td>
      <td className={`${headerCellClass} text-slate-700 dark:text-slate-200`}>{fmtQty(String(group.tasks.reduce((s, t) => s + parseFloat(t.cache.issued_quantity), 0)))}</td>
      <td className={`${headerCellClass} text-slate-700 dark:text-slate-200`}>
        {groupInput ? (
          <span className="flex items-center gap-1">
            <DraftQtyInput
              value={groupQty?.good ?? ""}
              onChange={(value) => onGroupQtyChange?.("good", value)}
              recorded={fmtQty(String(recordedGood))}
              ariaLabel={`${firstTask.product_sku}: годные группы`}
              issueText={groupIssue?.good ?? null}
              overPlan={overPlan.good}
            />
            {overPlan.good && (
              <span aria-hidden className="text-[10px] leading-none text-amber-600" title="Сверх плана">
                ▲
              </span>
            )}
          </span>
        ) : (
          fmtQty(String(group.totalQtyDone))
        )}
      </td>
      <td className={`${headerCellClass} text-slate-700 dark:text-slate-200`}>
        {groupInput ? (
          <span className="flex items-center gap-1">
            <DraftQtyInput
              value={groupQty?.defect ?? ""}
              onChange={(value) => onGroupQtyChange?.("defect", value)}
              recorded={fmtQty(String(recordedDefect))}
              ariaLabel={`${firstTask.product_sku}: брак группы`}
              issueText={groupIssue?.defect ?? null}
              overPlan={overPlan.defect}
            />
            {overPlan.defect && (
              <span aria-hidden className="text-[10px] leading-none text-amber-600" title="Сверх плана">
                ▲
              </span>
            )}
          </span>
        ) : (
          fmtQty(String(recordedDefect))
        )}
      </td>
      <td className={`${headerCellClass} text-slate-700 dark:text-slate-200`}>{fmtQty(String(group.tasks.reduce((s, t) => s + parseFloat(t.cache.transferred_quantity), 0)))}</td>
      <td className={`${headerCellClass} text-slate-700 dark:text-slate-200`}>{fmtQty(String(group.tasks.reduce((s, t) => s + parseFloat(t.cache.remaining_quantity), 0)))}</td>
      <td className={headerCellClass}>
        <div className="flex items-center gap-1">
          <Badge variant="secondary" className={`${ROW_BADGE_CLASS} font-bold`}>
            &times;{group.tasks.length}
          </Badge>
          {isBulkMode && header.allSelected && (
            <span className={`text-xs ${TABLE_ROW_STYLES.selectedLabel}`}>выбрано</span>
          )}
        </div>
      </td>
      <td className={`${headerCellClass} ${isBulkMode && allSelected ? TABLE_ROW_STYLES.selectedGroupHeader : TABLE_ROW_STYLES.defaultGroupRow}`} />
      <TableCornerResetCell className={TABLE_ROW_STYLES.groupHeaderCell} />
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
  /**
   * Массовый ввод факта (#283): черновик страницы. У выделенной строки ячейки
   * «Годные»/«Брак» становятся полями, ввод в шапке группы раскладывается по
   * её строкам. Без него доска работает как прежде.
   */
  bulkDraft?: BulkDraft;
  onBulkDraftChange?: (draft: BulkDraft) => void;
  /** Причина отклонённого ввода — её текстом показывает футер (ADR-0032). */
  /**
   * id строк, видимых на доске сейчас (фильтр и сортировка применены): по ним
   * футер считает «вне текущего фильтра: N». Доска — единственный, кто знает,
   * что отрисовано, поэтому публикует список наружу.
   */
  onVisibleTaskIdsChange?: (ids: number[]) => void;
  /**
   * Есть ли у участка упаковочные операции (`Section.has_packaging`). На
   * участке без них колонки «Упаковка» нет ни в шапке, ни в строке, ни в
   * карточке — иначе пустая колонка читается как «данные не пришли».
   */
  hasPackaging?: boolean;
  /**
   * Узлы вызывающего экрана сразу после поля поиска — фильтр периода и печать.
   * Место фиксирует доска: справа (в `actions`) они оказываются в стороне от
   * того, что фильтруют.
   */
  toolbar?: ReactNode;
  /**
   * Значения поповеров из серверного справочника (#211): приходят готовыми от
   * вызывающего экрана и приоритетнее страничных. Страничные остаются для
   * колонок, которые фильтрует сам экран (ADR-0044) и для которых справочника
   * нет — иначе «Нет значений» означало бы «нет на этой странице».
   */
  filterValueOptions?: Partial<Record<TaskSortField, string[]>>;
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
      /** Ключ группы строки — по нему снимается набранное в её поле. */
      groupKey?: string;
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
  bulkDraft,
  onBulkDraftChange,
  onVisibleTaskIdsChange,
  hasPackaging,
  toolbar,
  filterValueOptions,
  page,
  setPage,
  limit,
  setLimit,
  totalPages,
  rangeLabel,
  onServerQueryChange,
}: SectionTasksBoardProps) {
  const tableScrollRef = useRef<HTMLDivElement>(null);
  // Колонки участка: «Упаковка» есть только там, где у участка есть
  // упаковочные операции. Число колонок служебных строк («В ожидании», пустое
  // состояние, распорки виртуализации) выводится из них же, а не константой:
  // забытое число оставляло служебную строку уже шапки, и полоса обрывалась,
  // не закрывая угол сброса фильтров. `+ 1` — этот угол.
  const visibleColumns = useMemo(() => visibleBoardColumns(hasPackaging), [hasPackaging]);
  const boardColspan = visibleColumns.length + 1;
  // Правило заглушки — общее для всех таблиц (ADR-0044), поэтому берётся из
  // shared, а не пишется здесь выражением: тринадцать копий однажды разъедутся.
  const showLoadingPlaceholder = isFirstRowsLoad(isLoading, tasks);
  /**
   * Набранное в поле группы, пока ввод не разложен. Поле группы выводится из
   * строк, но «факт станет N» при N меньше записанного разложить нельзя — а
   * набранное обязано остаться в поле, иначе цифру не добрать посимвольно.
   * Снимается правкой любой строки группы: тогда поле снова выводится из строк.
   */
  const [groupInputs, setGroupInputs] = useState<Record<string, DraftQty>>({});
  const [searchQuery, setSearchQuery] = useState("");
  const debouncedSearch = useDebouncedValue(searchQuery);
  const {
    bindColumn,
    columnFilters,
    columnSearchQueries,
    debouncedColumnSearchQueries,
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
        columnSearchQueries: debouncedColumnSearchQueries,
        sortConfigs,
      }),
    );
  }, [debouncedSearch, columnFilters, debouncedColumnSearchQueries, sortConfigs, onServerQueryChange]);

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

  // Строки, отрисованные сейчас: по ним футер считает «вне текущего фильтра».
  useEffect(() => {
    onVisibleTaskIdsChange?.(visibleTasks.map((task) => task.id));
  }, [visibleTasks, onVisibleTaskIdsChange]);

  /**
   * Контекст ввода строки. Инпуты живут только у выделенных строк (#283), а
   * потолок строки считается `taskFactCeiling`: у раскроя это остаток входа,
   * у остальных — «в работе плюс доступное к довыдаче».
   */
  const draftContextFor = (
    task: SectionBoardTask,
    groupKey?: string,
  ): RowDraftContext | undefined => {
    if (!bulkMode || !bulkDraft || !onBulkDraftChange || !bulkSelection?.isSelected(task.id)) {
      return undefined;
    }
    const value = draftQtyFor(bulkDraft, task.id);
    const ceiling = taskFactCeiling(task);
    return {
      value,
      // Превышение считается по порции, а не по набранному числу: «факт станет
      // 500» при записанных 400 — это порция 100, и потолок ей не 500.
      overPlan: {
        good: factPortion(value.good, recordedFact(task, "good")) > ceiling,
        defect: factPortion(value.defect, recordedFact(task, "defect")) > ceiling,
      },
      issue: {
        good: draftFieldIssue(task, value.good, "good"),
        defect: draftFieldIssue(task, value.defect, "defect"),
      },
      onChange: (field, next) => {
        // Правка строки снимает набранное в поле группы: поле выводится из
        // строк, и оставленное «набранное» разошлось бы с раскладкой.
        if (groupKey) setGroupInputs((prev) => forgetGroupInput(prev, groupKey));
        onBulkDraftChange(withDraftField(bulkDraft, task.id, field, next));
      },
    };
  };

  /**
   * Групповой ввод: набранное в шапке раскладывается по строкам группы
   * последовательно. Раскладываются только доводимые строки — ожидающие и
   * завершённые ввод не принимают, и без этого дефицит съедал бы строку,
   * которую всё равно нельзя завершить. Групповое поле — это и выбор группы
   * целиком: результат виден в строках, а инпуты живут у выделенных строк.
   */
  const handleGroupQtyChange = (
    tasks: SectionBoardTask[],
    field: DraftField,
    value: string,
    groupKey: string,
  ) => {
    if (!bulkDraft || !onBulkDraftChange) return;
    const completable = tasks.filter((task) => getCompletionBlockReason(task) === null);
    const { resolution } = resolveGroupFact(completable, field, value);
    if (value.trim() === "") {
      // Очистка поля снимает раскладку: строки возвращаются к плейсхолдерам.
      setGroupInputs((previous) => forgetGroupInput(previous, groupKey));
      onBulkDraftChange(applyGroupField(bulkDraft, completable, field, ""));
    } else if (resolution.kind === "write") {
      setGroupInputs((previous) => forgetGroupInput(previous, groupKey));
      onBulkDraftChange(applyGroupField(bulkDraft, completable, field, value));
    } else {
      // Ввод ещё не применён (недонабран или неприменим) — набранное остаётся
      // в поле группы: поле выводится из строк, и без этого «+» терялся бы при
      // посимвольном наборе, а цель ниже записанного исчезала бы из поля.
      setGroupInputs((previous) => ({
        ...previous,
        [groupKey]: { ...(previous[groupKey] ?? EMPTY_DRAFT_QTY), [field]: value },
      }));
    }
    for (const task of completable) {
      bulkSelection?.selectOne(task.id, true);
    }
  };

  /**
   * Значение группового поля выводится из строк, а не хранится отдельно: так
   * набранное и разложенное не расходятся, и правка отдельной строки видна в
   * шапке. Пусто во всех строках — поле показывает плейсхолдер с записанным
   * фактом.
   */
  /** Значение поля группы: набранное, пока оно не разложено, иначе — из строк. */
  const groupFieldValue = (
    tasks: SectionBoardTask[],
    field: DraftField,
    groupKey: string,
  ): string => {
    if (!bulkDraft) return "";
    return groupInputs[groupKey]?.[field] ?? groupDraftValueOf(tasks, bulkDraft, field);
  };

  /** Причина домена в поле группы — тот же текст, что у поля строки. */
  const groupFieldIssue = (
    tasks: SectionBoardTask[],
    field: DraftField,
    groupKey: string,
  ): string | null => {
    const value = groupFieldValue(tasks, field, groupKey);
    if (value.trim() === "") return null;
    const { resolution } = resolveGroupFact(tasks, field, value);
    return resolution.kind === "invalid" ? actionReasonText(resolution.reason) : null;
  };

  const groupOverPlan = (tasks: SectionBoardTask[]): { good: boolean; defect: boolean } => {
    if (!bulkDraft) return { good: false, defect: false };
    let good = false;
    let defect = false;
    for (const task of tasks) {
      const qty = draftQtyFor(bulkDraft, task.id);
      const ceiling = taskFactCeiling(task);
      if (factPortion(qty.good, recordedFact(task, "good")) > ceiling) good = true;
      if (factPortion(qty.defect, recordedFact(task, "defect")) > ceiling) defect = true;
    }
    return { good, defect };
  };

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
      ...(toolbar ? [{ kind: "custom" as const, key: "toolbar", node: toolbar, layoutSpan: "flex-shrink-0" }] : []),
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
  }, [mode, onModeChange, searchQuery, bulkMode, onBulkModeChange, modeCounts, readOnly, showCompletedStatus, showStatusFilters, toolbar]);

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

      // В массовом режиме группа раскрыта, когда в ней есть выделенная строка:
      // раскрытие — следствие выбора, а не входа в режим. Сам вход в групповые
      // операции ничего не раскрывает (свёрнутая группа остаётся свёрнутой),
      // а выделение группы целиком раскрывает её строки; снятие выбора с
      // последней строки возвращает группу к прежнему состоянию.
      const hasSelectedRow =
        bulkMode && group.tasks.some((task) => bulkSelection?.isSelected(task.id) === true);
      const isCollapsed = hasSelectedRow ? false : collapsedGroups.has(entry.key);
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
            groupKey: entry.key,
          });
        });
      }
    }
    return items;
    // `bulkMode` — в зависимостях: в массовом режиме раскрытие группы зависит
    // от выделения, и без него список строк не пересчитался бы при включении
    // режима. `bulkSelection` — по той же причине: выделение строки раскрывает
    // её группу.
  }, [boardEntries, collapsedGroups, bulkMode, bulkSelection]);

  const renderWaitingDivider = useCallback((row: Extract<VirtualBoardRow, { kind: "divider" }>) => (
    <tr key={row.key} data-testid="waiting-divider">
      <td colSpan={boardColspan} className="p-0" style={{ height: ROW_HEIGHT_PX }}>
        <div className={`flex ${TABLE_ROW_DENSE.divider} items-center gap-2 border-y border-amber-200 bg-amber-50/70 px-2`}>
          <span className="text-[11px] font-semibold uppercase tracking-wide text-amber-800">
            В ожидании
          </span>
          <span className="text-[11px] tabular-nums text-amber-800/70">{row.count}</span>
          <span className="h-px flex-1 bg-amber-200" />
        </div>
      </td>
    </tr>
  ), [boardColspan]);

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
            hasPackaging={hasPackaging}
            groupQty={{
              good: groupFieldValue(row.group.tasks, "good", row.entryKey),
              defect: groupFieldValue(row.group.tasks, "defect", row.entryKey),
            }}
            groupIssue={{
              good: groupFieldIssue(row.group.tasks, "good", row.entryKey),
              defect: groupFieldIssue(row.group.tasks, "defect", row.entryKey),
            }}
            groupOverPlan={groupOverPlan(row.group.tasks)}
            onGroupQtyChange={
              bulkMode && onBulkDraftChange
                ? (field, value) => handleGroupQtyChange(row.group.tasks, field, value, row.entryKey)
                : undefined
            }
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
        hasPackaging,
        draftContextFor(row.task, row.groupKey),
      );
    },
    [
      bulkMode,
      bulkSelection,
      bulkDraft,
      hasPackaging,
      handleGroupQtyChange,
      onAction,
      onBulkDraftChange,
          onRevokeItem,
      readOnly,
      renderWaitingDivider,
      revokeSelection,
      toggleGroup,
    ],
  );

  const headerCellClass = cn(
    DATA_TABLE_STYLES.headerRow,
    DATA_TABLE_STYLES.headerCell,
    TABLE_ROW_COMPACT.headerCell,
  );

  const activeFilterSummary = useMemo(
    () =>
      buildActiveFilterSummary(searchQuery, sortConfigs.length, {
        columnFilters,
        columnSearchQueries,
        columnLabels: Object.fromEntries(
          boardColumns.filter((c) => c.filterField).map((c) => [c.filterField, c.label]),
        ),
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

      {/* Заглушка — только пока заданий на экране не было ни разу. Дальше дерево
          остаётся на месте, а смену страницы и фильтров показывает
          `isFetching` вызывающего экрана: иначе размонтирование уносит с собой
          открытый поповер и набранный в нём текст (ADR-0044). */}
      {showLoadingPlaceholder && <div className="rounded-lg border p-4 text-sm text-muted-foreground">Загрузка задач...</div>}
      {!showLoadingPlaceholder && total === 0 && (
        <div className="rounded-lg border p-4 text-sm text-muted-foreground text-center">
          Нет задач в выбранном режиме
        </div>
      )}

      {!showLoadingPlaceholder && total > 0 && (
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
                  {visibleColumns.map((column) => (
                    <th
                      key={column.id}
                      className={`${headerCellClass} ${column.className ?? "text-left"}`}
                      aria-sort={column.sortField ? getAriaSort(sortConfigs, column.sortField) : undefined}
                    >
                      <DataTableColumnHeader
                        column={column}
                        bindColumn={bindColumn}
                        values={
                          column.filterField
                            ? filterValueOptions?.[column.filterField] ?? uniqueValues[column.filterField]
                            : undefined
                        }
                        currentSorts={sortConfigs}
                        onSortChange={handleSortChange}
                      />
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
                    <td colSpan={boardColspan} className="p-8 text-center text-sm text-muted-foreground">
                      Нет задач, соответствующих фильтру
                    </td>
                  </tr>
                </tbody>
              ) : (
                <VirtualizedTableBody
                  rows={virtualRows}
                  rowHeight={ROW_HEIGHT_PX}
                  colSpan={boardColspan}
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
              const isCollapsed = bulkMode ? false : collapsedGroups.has(entry.key);
              const isSingleTask = group.tasks.length === 1;

              // Одна задача — рендерим напрямую без шапки группы
              if (isSingleTask) {
                const task = group.tasks[0];
                const isSelected = revokeSelection
                  ? revokeSelection.isSelected(task.id)
                  : bulkMode && bulkSelection?.isSelected(task.id);
                return renderMobileCard(task, isSelected, bulkMode, bulkSelection, onAction, onRevokeItem, isRevoking, true, readOnly, hasPackaging, draftContextFor(task));
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
                    </div>
                  </div>
                  {/* Групповой ввод на узком экране — те же два поля, что и в
                      шапке таблицы: отдельной мобильной модели нет (#283, п. 7). */}
                  {bulkMode && onBulkDraftChange && !readOnly && (
                    <div
                      className="flex flex-wrap items-end gap-3 border-b border-muted px-3 py-2"
                      onClick={(event) => event.stopPropagation()}
                    >
                      {([
                        ["good", "Годные группы"],
                        ["defect", "Брак группы"],
                      ] as const).map(([field, label]) => {
                        const value = groupFieldValue(group.tasks, field, entry.key);
                        const recorded =
                          field === "good"
                            ? group.tasks.reduce((sum, task) => sum + parseFloat(task.cache.completed_quantity), 0)
                            : group.tasks.reduce((sum, task) => sum + parseFloat(task.cache.rejected_quantity), 0);
                        return (
                          <label key={field} className="flex flex-col gap-0.5 text-[11px] text-muted-foreground">
                            {label}
                            <DraftQtyInput
                              value={value}
                              onChange={(next) => handleGroupQtyChange(group.tasks, field, next, entry.key)}
                              recorded={fmtQty(String(recorded))}
                              ariaLabel={`${group.label}: ${label}`}
                              issueText={groupFieldIssue(group.tasks, field, entry.key)}
                              overPlan={groupOverPlan(group.tasks)[field]}
                            />
                          </label>
                        );
                      })}
                    </div>
                  )}
                  {!isCollapsed && <div className="divide-y divide-muted">{group.tasks.map((task, idx) => {
                    const isLast = idx === group.tasks.length - 1;
                    const isSelected = revokeSelection
                      ? revokeSelection.isSelected(task.id)
                      : bulkMode && bulkSelection?.isSelected(task.id);
                    return renderMobileCard(task, isSelected, bulkMode, bulkSelection, onAction, onRevokeItem, isRevoking, isLast, readOnly, hasPackaging, draftContextFor(task, entry.key));
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
