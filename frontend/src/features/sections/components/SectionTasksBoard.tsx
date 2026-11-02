/**
 * components/SectionTasksBoard.tsx
 * =================================
 * Доска задач одного участка производства.
 *
 * Сохраняет весь старый функционал (режимы, bulk, действия) +
 * использует новый groupTasksByProfile вместо BoardRowItem.
 */

import { useMemo, useState, useCallback, useEffect, useRef, type ReactNode } from "react";
import { Check, CheckCheck, ChevronDown, ChevronRight } from "lucide-react";
import type { SectionBoardQueryParams, SectionBoardTask, TaskGroup } from "@/shared/api/shopfloor";
import { formatDimensionsLabel } from "@/shared/api/stock";
import {
  Badge,
  ActionWithReason,
  Button,
  CutLayoutCell,
  DataTableColumnHeader,
  FiltersPanel,
  MobileScrollTable,
  MOBILE_TABLE_MIN_WIDTH_CLASS,
  TableCornerResetCell,
  TableCornerResetHeader,
  TablePaginationFooter,
  VirtualizedTableBody,
  DATA_TABLE_STYLES,
  buildActiveFilterSummary,
  stickyCell,
  type FiltersPanelField,
} from "@/shared/ui";
import type { ColumnSortDef } from "@/shared/hooks/useTableQueryEngine";
import type { PageLimitOption } from "@/shared/hooks/usePaginatedTableQuery";
import { useFilterableTable } from "@/shared/hooks/useFilterableTable";
import {
  buildColumnFilterPredicate,
  buildColumnFilterValues,
} from "@/shared/lib/columnSpecs";
import { useDebouncedValue } from "@/shared/lib/useDebouncedValue";
import { useMediaQuery } from "@/shared/lib/useMediaQuery";
import { getAriaSort } from "@/shared/lib/multiSort";
import { isFirstRowsLoad } from "@/shared/lib/tableQueryPlaceholder";
import {
  buildBoardServerQueryParams,
  isServerSortField,
  type TaskSortField,
} from "../lib/boardQueryParams";
import { toggleSelectionOnRowKey } from "../lib/boardRowKeydown";
import { groupTasksByProfile, sortGroupsByQuantityAndSize, taskGroupingDimensions } from "../lib/groupTasksByProfile";
import { clusterByArticle } from "@/shared/lib/clusterByArticle";
import type { GroupingProfile } from "../lib/groupingProfiles";
import {
  getCompletionBlockReason,
  getTaskRowState,
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
  packagingBreakdownLabel,
  taskOperations,
} from "../lib/taskView";
import {
  TaskStatusDot,
  buildTaskViewFields,
  getTaskGroupRailClass,
  getTaskRowClass,
  getTaskStripeClass,
  type TaskViewFieldKey,
} from "./TaskView";
import { TABLE_ROW_STYLES } from "@/shared/lib/tableRowStyles";
import { TABLE_ROW_COMPACT, TABLE_ROW_DENSE } from "@/shared/lib/dataTableStyles";
import { actionReasonText } from "@/shared/lib/actionReasons";
import { factPortion, resolveFactQuantity } from "../lib/factQuantity";
import { cn } from "@/shared/utils/cn";
import { fmtQty, toQtyInteger } from "@/shared/lib/quantityFormat";
import { boardColumns, mobileBoardColumns, visibleBoardColumns, type BoardColumn } from "../lib/boardColumns";
import { buildTaskGroupView, type TaskGroupView } from "../lib/boardGroupView";

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
  const category = getTaskRowState(task).category;
  if (mode.active && category === "active") return true;
  if (mode.waiting && category === "waiting") return true;
  if (mode.completed && category === "completed") return true;
  return false;
}

function getStatusPriority(task: SectionBoardTask): number {
  const category = getTaskRowState(task).category;
  if (category === "active") return 0;
  if (category === "waiting") return 1;
  if (category === "completed") return 2;
  return 3;
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
 * Действие в закреплённой колонке на телефоне — пиктограмма, подпись уходит в
 * `aria-label` (#345). Колонка «Действия» делит кадр 390px с закреплённой
 * колонкой «Артикул» и напечатанной причиной недоступности (её нельзя ни
 * перенести, ни обрезать: #193, а высота строки фиксирована ADR-0030), и
 * текстовая подпись выталкивала кнопку за кадр — на шапке группы действия
 * наезжали на «Артикул». Слово не теряется: оно остаётся в доступном имени
 * и в `title`.
 */
const ROW_ACTION_LABEL_CLASS = "max-md:hidden";
const ROW_ACTION_ICON_CLASS = "h-4 w-4 shrink-0 md:hidden";

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
 * без наведения знаком со подсказкой — в плотной строке места на слова нет.
 *
 * Раскладка одна: телефонная таблица (#345) — та же строка доски, а не
 * карточка со своим набором подписей.
 */
function renderDraftCell(
  task: SectionBoardTask,
  cell: "completed" | "rejected",
  draft: RowDraftContext,
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
    <span className="flex items-center gap-1">
      <DraftQtyInput
        value={draft.value[field]}
        onChange={(next) => draft.onChange(field, next)}
        recorded={fmtQty(recorded)}
        ariaLabel={`${task.product_sku}: ${label}`}
        issueText={draft.issue[field]}
        overPlan={overPlan}
      />
      {overPlan && (
        <span
          aria-hidden
          className="text-[10px] leading-none text-amber-600"
          title={`Сверх плана: доступно на задачу ${fmtQty(taskFactCeiling(task))} шт.`}
        >
          ▲
        </span>
      )}
    </span>
  );
}

/**
 * Контекст массового ввода для выделенной строки. `undefined` — строка не
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

// ---------------------------------------------------------------------------
// Раскладки строки: десктоп и телефон — одна таблица, разный порядок колонок
// ---------------------------------------------------------------------------

/**
 * Телефонная раскладка строки (#345, ADR-0067). Механика закрепления и свайпа
 * живёт в `shared/ui/MobileScrollTable`; здесь — только имена колонок, ширины
 * и подложка.
 *
 * Ширины объявлены явно: «липкая» ячейка фиксируется краем, а не содержимым, и
 * длинный артикул растянул бы профиль на пол-экрана, вытеснив «Действия».
 * `w-px` у действия — приём auto-раскладки: явная крошечная ширина не
 * растягивает колонку, остальное забирают прокручиваемые.
 */
type BoardTableVariant = "desktop" | "mobile";

/**
 * Колонка доски → поле представления задания. Имена колонок несут суффикс
 * `Qty` («plannedQty»), а поля задания — нет («planned»): до #345 строку
 * собирал ручной перечень, и это несоответствие жило только в нём. Табличная
 * раскладка берёт значение по колонке, поэтому соответствие объявлено здесь
 * один раз.
 */
const FIELD_KEY_BY_COLUMN: Record<string, TaskViewFieldKey> = {
  plannedQty: "planned",
  issuedQty: "issued",
  completedQty: "completed",
  rejectedQty: "rejected",
  transferredQty: "transferred",
  remainingQty: "remaining",
};

function fieldKeyOf(columnId: string): TaskViewFieldKey {
  return FIELD_KEY_BY_COLUMN[columnId] ?? (columnId as TaskViewFieldKey);
}

const MOBILE_PROFILE_WIDTH_CLASS =
  "max-md:w-[112px] max-md:min-w-[112px] max-md:max-w-[112px] max-md:overflow-hidden";
const MOBILE_ACTIONS_WIDTH_CLASS = "max-md:w-px max-md:px-1";

/**
 * Непрозрачная подложка закреплённых ячеек: под липкую ячейку уезжает остальная
 * таблица, и полупрозрачный тон строки (`bg-blue-50/20`, `bg-amber-50/30`)
 * просвечивал бы чужими числами. На десктопе классов нет вовсе.
 */
const STICKY_HEADER_FILL = "max-md:bg-muted";
const STICKY_ROW_FILL = "max-md:bg-card";
const STICKY_GROUP_FILL = "max-md:bg-slate-100 dark:max-md:bg-slate-800";
const STICKY_SELECTED_FILL = "max-md:bg-blue-100 dark:max-md:bg-blue-950";

/** Закрепление колонки: только на телефоне — на десктопе раскладка прежняя. */
function mobileStickyProps(
  columnId: string,
  variant: BoardTableVariant,
  header: boolean,
  fill: string,
) {
  if (variant !== "mobile") return undefined;
  if (columnId === "productSku") {
    return stickyCell({
      name: "profile",
      side: "left",
      header,
      className: cn(MOBILE_PROFILE_WIDTH_CLASS, fill),
    });
  }
  if (columnId === "actions") {
    return stickyCell({
      name: "actions",
      side: "right",
      header,
      className: cn(MOBILE_ACTIONS_WIDTH_CLASS, fill),
    });
  }
  return undefined;
}

/** Шеврон раскрытия группы. На телефоне живёт в закреплённом профиле. */
function groupChevron(
  view: TaskGroupView,
  onToggleCollapse: () => void,
  tone: "desktop" | "mobile",
) {
  return (
    <button
      type="button"
      className={
        tone === "mobile"
          ? "p-0.5 hover:bg-muted/50 rounded transition-colors cursor-pointer"
          : "p-0.5 hover:bg-slate-200 rounded transition-colors text-slate-500 hover:text-slate-800 dark:text-slate-400 dark:hover:bg-slate-700 dark:hover:text-slate-100"
      }
      onClick={(event) => {
        event.stopPropagation();
        onToggleCollapse();
      }}
      title={view.collapseTitle}
    >
      {view.isCollapsed ? (
        <ChevronRight
          className={tone === "mobile" ? "h-4 w-4 text-muted-foreground" : "h-4 w-4 shrink-0"}
        />
      ) : (
        <ChevronDown
          className={tone === "mobile" ? "h-4 w-4 text-muted-foreground" : "h-4 w-4 shrink-0"}
        />
      )}
    </button>
  );
}

function renderTaskRow(
  task: SectionBoardTask,
  columns: BoardColumn[],
  variant: BoardTableVariant,
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
  const fieldByKey = new Map(fields.map((field) => [field.key, field] as const));
  const blockReason = getCompletionBlockReason(task);  // Рёбра блока живут на ячейках, а не на `<tr>`: таблица объявлена
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
  const rowState = getTaskRowState(task);
  const stickyFill =
    bulkMode && isSelected ? STICKY_SELECTED_FILL : isInGroup ? STICKY_GROUP_FILL : STICKY_ROW_FILL;

  const handleAction = (type: TaskActionDialogType) => {
    onAction(type, task);
  };

  const cellContent = (columnId: string, isLead: boolean): ReactNode => {
    switch (columnId) {
      case "statusDot":
        return (
          <>
            {/* Направляющая блока: строка связана с шевроном группы и с
                соседями. У последней строки она обрывается на своей точке —
                блок имеет конец, а не продолжается в следующую группу. На
                телефоне шеврон живёт в профиле, и направляющей здесь нет. */}
            {variant === "desktop" && isInGroup && (
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
          </>
        );
      case "productSku":
        return <span className="font-medium max-md:block max-md:truncate">{task.product_sku}</span>;
      case "status":
        return (
          <Badge variant="secondary" className={cn(rowState.badgeClass, ROW_BADGE_CLASS)}>
            {rowState.label}
          </Badge>
        );
      case "actions":
        return onRevokeItem ? (
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
              // Доступное имя — на всех ширинах: на телефоне подпись свёрнута в
              // пиктограмму, но кнопка обязана называться тем же словом.
              aria-label="Завершить"
              onClick={() => handleAction("complete")}
              disabled={blockReason !== null}
              title={blockReason ? actionReasonText(blockReason) : "Завершить задачу"}
            >
              <Check className={ROW_ACTION_ICON_CLASS} aria-hidden />
              <span className={ROW_ACTION_LABEL_CLASS}>Завершить</span>
            </Button>
          </ActionWithReason>
        );
      default: {
        const field = fieldByKey.get(fieldKeyOf(columnId));
        if (!field) return null;
        const key = fieldKeyOf(columnId);
        if (draft && (key === "completed" || key === "rejected")) {
          return renderDraftCell(task, key, draft);
        }
        return field.node;
      }
    }
  };

  return (
    <tr
      data-row-kind="board-task"
      // id задачи — адрес строки для e2e массового ввода (#283): строки одного
      // артикула неразличимы по тексту. Атрибут один на обе раскладки: строка
      // и на телефоне — `<tr>`.
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
        // Статус отбор не ограничивает: «ожидает предыдущего участка» —
        // допустимый кандидат дневного плана (в плане запрещены только
        // терминальные задания), и шапка группы такие строки уже выделяет.
        // Незавершаемые строки массовый ввод пропускает сам — их отсеивает
        // `isTaskCompletable` в черновике.
        if (bulkMode && bulkSelection) {
          bulkSelection.selectOne(task.id);
        }
      }}
      onKeyDown={(event) => {
        if (!bulkMode || !bulkSelection) return;
        toggleSelectionOnRowKey(event, () => bulkSelection.selectOne(task.id));
      }}
    >
      {columns.map((column, index) => {
        const isLead = index === 0;
        const field = fieldByKey.get(fieldKeyOf(column.id));
        const sticky = mobileStickyProps(column.id, variant, false, stickyFill);
        return (
          <td
            key={column.id}
            data-column={column.id}
            {...sticky}
            className={cn(
              cellClass,
              isLead && getTaskStripeClass(task),
              isLead && "relative",
              column.id === "statusDot" && "text-center",
              field?.cellClass,
              column.id === "statusDot" && "max-md:max-w-[28px]",
              sticky?.className,
            )}
          >
            {cellContent(column.id, isLead)}
          </td>
        );
      })}
      {variant === "desktop" && <TableCornerResetCell className={edgeClass || undefined} />}
    </tr>
  );
}

// ---------------------------------------------------------------------------
// Шапка группы: одна на обе раскладки
// ---------------------------------------------------------------------------

/**
 * Шапка группы. Суммы, выделение, свёрнутость и причина недоступности
 * завершения приходят готовыми из `buildTaskGroupView`: разметка ничего не
 * складывает и не решает (ревью #283 п. 2 — суммы считались дважды, в шапке
 * таблицы и в шапке карточки, и расходились на разборе `parseFloat`).
 *
 * Раскладка — те же колонки, что у строки задания: на телефоне профиль
 * закреплён слева, «Действия» справа, остальное едет под свайпом (#345).
 */
function BoardTaskGroupRow({
  group,
  view,
  columns,
  variant,
  isBulkMode,
  onToggleCollapse,
  onSelectGroup,
  onCompleteGroup,
  groupQty,
  groupIssue,
  groupOverPlan,
  onGroupQtyChange,
}: {
  group: TaskGroup;
  view: TaskGroupView;
  columns: BoardColumn[];
  variant: BoardTableVariant;
  isBulkMode: boolean;
  onToggleCollapse: () => void;
  onSelectGroup: () => void;
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
  /**
   * «Завершить группу»: групповой путь завершения — диалог с суммой факта и
   * брака по всем заданиям группы. Не задан — кнопки нет (вкладка плана).
   */
  onCompleteGroup?: (group: TaskGroup) => void;
}) {
  const { firstTask } = view;
  const groupInput = Boolean(isBulkMode && onGroupQtyChange);
  const overPlan = groupOverPlan ?? { good: false, defect: false };
  // Рёбра блока — на ячейках: границы `<tr>` в таблице доски (`border-separate`)
  // браузер не рисует, и `border-y` на строке был невидим.
  const headerCellClass = cn(ROW_CELL_CLASS, TABLE_ROW_STYLES.groupHeaderCell);
  const stickyFill = isBulkMode && view.allSelected ? STICKY_SELECTED_FILL : STICKY_GROUP_FILL;
  const railClass = getTaskGroupRailClass(group.tasks);
  const captionClass = "text-xs font-medium text-slate-500 dark:text-slate-400";

  /** Поле группового ввода: введённое раскладывается по строкам группы. */
  const groupInputCell = (field: DraftField) => {
    const label = field === "good" ? "годные группы" : "брак группы";
    const issue = field === "good" ? groupIssue?.good : groupIssue?.defect;
    const marked = overPlan[field];
    return (
      <span className="flex items-center gap-1">
        <DraftQtyInput
          value={groupQty?.[field] ?? ""}
          onChange={(value) => onGroupQtyChange?.(field, value)}
          recorded={fmtQty(String(field === "good" ? view.goodQty : view.defectQty))}
          ariaLabel={`${firstTask.product_sku}: ${label}`}
          issueText={issue ?? null}
          overPlan={marked}
        />
        {marked && (
          <span aria-hidden className="text-[10px] leading-none text-amber-600" title="Сверх плана">
            ▲
          </span>
        )}
      </span>
    );
  };

  const cellContent = (columnId: string): ReactNode => {
    switch (columnId) {
      case "statusDot":
        // Шеврон группы на десктопе — в первой колонке, как и раньше. На
        // телефоне он живёт в закреплённом профиле: точка статуса уезжает
        // вправо вместе с вторичными колонками и шеврон там был бы недоступен.
        if (variant !== "desktop") return null;
        return (
          <>
            {/* Спуск от шеврона к строкам: без него направляющая блока
                начинается ниоткуда и читается как случайная линия. У свёрнутой
                группы строк нет — нет и спуска. */}
            {!view.isCollapsed && (
              <span
                aria-hidden
                className={cn(
                  "pointer-events-none absolute bottom-0 left-1/2 h-2 w-0.5 -translate-x-1/2",
                  TABLE_ROW_STYLES.groupConnector,
                )}
              />
            )}
            <div className="relative z-10 flex items-center justify-center">
              {groupChevron(view, onToggleCollapse, "desktop")}
            </div>
          </>
        );
      case "productSku":
        return (
          <span className="flex min-w-0 items-center gap-1">
            {variant === "mobile" && groupChevron(view, onToggleCollapse, "mobile")}
            <span className="truncate">{firstTask.product_sku}</span>
            <Badge variant="secondary" className={cn(ROW_BADGE_CLASS, "shrink-0 font-bold")}>
              &times;{view.taskCount}
            </Badge>
            {isBulkMode && view.allSelected && (
              <span className={cn("hidden text-xs sm:inline", TABLE_ROW_STYLES.selectedLabel)}>
                выбрано
              </span>
            )}
          </span>
        );
      case "dimensions":
        return (
          <span className={captionClass}>
            {formatDimensionsLabel(taskGroupingDimensions(firstTask))}
          </span>
        );
      case "operation":
        return (
          <span className={captionClass}>
            {firstTask.transforms_dimensions ? (
              <CutLayoutCell
                layout={firstTask.cut_layout}
                fallback={formatDimensionsLabel(taskGroupingDimensions(firstTask))}
              />
            ) : (
              taskOperations(firstTask).join(" · ") || "—"
            )}
          </span>
        );
      case "packaging":
        return (
          <span className={captionClass}>{packagingBreakdownLabel(group.tasks, fmtQty)}</span>
        );
      case "plannedQty":
        return fmtQty(String(view.planQty));
      case "issuedQty":
        return fmtQty(String(view.issuedQty));
      case "completedQty":
        return groupInput ? groupInputCell("good") : fmtQty(String(view.goodQty));
      case "rejectedQty":
        return groupInput ? groupInputCell("defect") : fmtQty(String(view.defectQty));
      case "transferredQty":
        return fmtQty(String(view.transferredQty));
      case "remainingQty":
        return fmtQty(String(view.remainingQty));
      case "actions":
        if (!onCompleteGroup) return null;
        return (
          <ActionWithReason reason={view.completeReason} layout="row">
            <Button
              variant="outline"
              className={ROW_ACTION_BUTTON_CLASS}
              aria-label="Завершить группу"
              onClick={(event) => {
                event.stopPropagation();
                onCompleteGroup(group);
              }}
              disabled={view.completableCount === 0}
              title={
                view.completeReason
                  ? actionReasonText(view.completeReason)
                  : "Завершить все задания группы: факт и брак раскладываются по строкам"
              }
            >
              <CheckCheck className={ROW_ACTION_ICON_CLASS} aria-hidden />
              <span className={ROW_ACTION_LABEL_CLASS}>Завершить группу</span>
            </Button>
          </ActionWithReason>
        );
      default:
        // «Статус» у группы не нужен: состояние блока несут рельс и тон строк.
        return null;
    }
  };

  return (
    <tr
      data-row-kind="board-group"
      style={{ height: ROW_HEIGHT_PX }}
      tabIndex={isBulkMode ? 0 : undefined}
      aria-selected={isBulkMode ? view.allSelected : undefined}
      className={`cursor-pointer transition-colors font-semibold ${isBulkMode && view.allSelected ? TABLE_ROW_STYLES.selectedGroupHeader : TABLE_ROW_STYLES.defaultGroupHeader}`}
      onClick={() => {
        if (isBulkMode) onSelectGroup();
        else onToggleCollapse();
      }}
      onKeyDown={(event) => {
        if (!isBulkMode) return;
        toggleSelectionOnRowKey(event, onSelectGroup);
      }}
    >
      {columns.map((column, index) => {
        const sticky = mobileStickyProps(column.id, variant, false, stickyFill);
        const isLead = index === 0;
        return (
          <td
            key={column.id}
            data-column={column.id}
            {...sticky}
            className={cn(
              headerCellClass,
              "text-slate-700 dark:text-slate-200",
              column.id === "statusDot" && "relative text-center",
              isLead && "relative",
              isLead && railClass,
              sticky?.className,
            )}
          >
            {cellContent(column.id)}
          </td>
        );
      })}
      {variant === "desktop" && (
        <TableCornerResetCell className={TABLE_ROW_STYLES.groupHeaderCell} />
      )}
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
   * «Завершить группу» в шапке блока: диалог с суммой факта и брака по всем
   * заданиям группы. Не задан — кнопки нет: у вкладки плана свой путь,
   * и групповое завершение там неуместно.
   */
  onCompleteGroup?: (group: TaskGroup) => void;
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
   * участке без них колонки «Упаковка» нет ни в шапке, ни в строке — иначе
   * пустая колонка читается как «данные не пришли».
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
  onCompleteGroup,
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
  /**
   * Один экран за раз. Порог совпадает с Tailwind `md` — ровно то, что решают
   * мобильные классы `max-md:`. До #345 ветки (таблица и карточки) строились
   * одновременно и прятались классами: двойная работа на каждом кадре и дубли
   * в дереве (одно задание рисовалось дважды).
   */
  const isDesktopViewport = useMediaQuery("(min-width: 768px)");
  const variant: BoardTableVariant = isDesktopViewport ? "desktop" : "mobile";
  /**
   * Колонки участка: «Упаковка» есть только там, где у неё есть упаковочные
   * операции, а на телефоне тот же набор идёт в порядке оператора (#345).
   * Число колонок служебных строк («В ожидании», пустое состояние, распорки
   * виртуализации) выводится из них же, а не константой: забытое число
   * оставляло служебную строку уже шапки. На десктопе `+ 1` — угол сброса
   * фильтров; на телефоне его нет — сброс живёт в ряду фильтров.
   */
  const columns = useMemo(
    () => (isDesktopViewport ? visibleBoardColumns(hasPackaging) : mobileBoardColumns(hasPackaging)),
    [isDesktopViewport, hasPackaging],
  );
  const boardColspan = columns.length + (isDesktopViewport ? 1 : 0);
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
      buildColumnFilterPredicate(
        clientFilterState.columnFilters,
        clientFilterState.columnSearchQueries,
        boardColumns,
      ),
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

  // Список значений попапера — из описания колонок: читатель значения у
  // попапера и у клиентского предиката один и тот же (`cellValue`).
  const uniqueValues = useMemo(
    () => buildColumnFilterValues(visibleTasks, boardColumns),
    [visibleTasks],
  );

  // Порядок строк доски. Колонки серверной сортировки (sequence/productSku/
  // status/dimensions) уже пришли в нужном порядке с сервера, остальные
  // клиент упорядочивает здесь, поверх ответа и до группировки. Без сортировки
  // действует дефолт «количество убыв., размер убыв.», а внутри группы —
  // «статус, затем sequence» (GLOSSARY.md, раздел «Сортировка строк по размеру»).
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

    const ordered = clusterByArticle(sortGroupsByQuantityAndSize(grouped), {
      articleOf: (group) => group.tasks[0]?.product_sku ?? "—",
      quantityOf: (group) => group.totalQtyPlan,
    });
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
    () => visibleTasks.filter((t) => getTaskRowState(t).category !== "waiting").map((t) => t.id),
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
    active: tasks.filter((t) => getTaskRowState(t).category === "active").length,
    waiting: tasks.filter((t) => getTaskRowState(t).category === "waiting").length,
    completed: tasks.filter((t) => getTaskRowState(t).category === "completed").length,
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

  /** Строка виртуализированного тела: разделитель, шапка группы или задание. */
  const renderVirtualRow = useCallback(
    (row: VirtualBoardRow) => {
      if (row.kind === "divider") return renderWaitingDivider(row);
      if (row.kind === "group") {
        // Состояние группы считается один раз и уходит в разметку готовым:
        // суммы, свёрнутость и причина завершения не складываются в JSX.
        const view = buildTaskGroupView(row.group, {
          isCollapsed: row.isCollapsed,
          isBulkMode: Boolean(bulkMode),
          allSelected: Boolean(
            bulkMode && bulkSelection?.isAllSelected(row.group.tasks.map((t) => t.id)),
          ),
        });
        return (
          <BoardTaskGroupRow
            key={row.key}
            group={row.group}
            view={view}
            columns={columns}
            variant={variant}
            isBulkMode={!!bulkMode}
            onToggleCollapse={() => toggleGroup(row.entryKey)}
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

      const isSelected = revokeSelection
        ? revokeSelection.isSelected(row.task.id)
        : bulkMode && bulkSelection?.isSelected(row.task.id);
      return renderTaskRow(
        row.task,
        columns,
        variant,
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
      columns,
      hasPackaging,
      handleGroupQtyChange,
      onAction,
      onBulkDraftChange,
      onRevokeItem,
      readOnly,
      renderWaitingDivider,
      revokeSelection,
      toggleGroup,
      variant,
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
        onReset={handleResetAllFilters}
        hasActiveFilters={hasTableFiltersActive}
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
          {/* Короткий текст без пояснений (#301): в режиме создания плана сюда
              попадает и случай «все задания заняты планами» — объяснять это
              мастеру незачем, он видит планы участка выше. Тем же текстом
              вкладка «Задания» отвечает на свои пустые состояния. */}
          Нет заданий
        </div>
      )}

      {!showLoadingPlaceholder && total > 0 && (
        <>
          {/* Одна таблица на оба экрана (#345): на телефоне — порядок
              оператора, «SKU/профиль» закреплён слева, «Действия» справа,
              между ними свайп; на десктопе — прежняя раскладка. Карточек
              задания больше нет: строка — это `<tr>` на любой ширине. */}
          <MobileScrollTable
            scrollRef={tableScrollRef}
            className={DATA_TABLE_STYLES.container}
            style={{ maxHeight: "70vh", overflow: "auto" }}
          >
            <table
              className={cn(
                "w-full border-separate border-spacing-0 text-sm",
                MOBILE_TABLE_MIN_WIDTH_CLASS,
              )}
            >
              <thead>
                <tr>
                  {columns.map((column) => {
                    const sticky = mobileStickyProps(column.id, variant, true, STICKY_HEADER_FILL);
                    return (
                      <th
                        key={column.id}
                        data-column={column.id}
                        {...sticky}
                        className={cn(
                          headerCellClass,
                          column.className ?? "text-left",
                          sticky?.className,
                        )}
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
                    );
                  })}
                  {/* Угол сброса фильтров — только десктоп: на телефоне он
                      оказался бы под закреплёнными «Действиями». Сброс там
                      живёт в ряду фильтров, рядом с поиском (ADR-0067). */}
                  {isDesktopViewport && (
                    <TableCornerResetHeader
                      hasActiveFilters={hasTableFiltersActive}
                      onReset={handleResetAllFilters}
                      dataTableHeader
                    />
                  )}
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
          </MobileScrollTable>

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
