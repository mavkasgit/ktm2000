/**
 * components/TaskView.tsx — раскладки представления задания.
 *
 * Тон, цвет точки, поля задания и состояние шапки группы считаются в
 * `lib/taskView`; здесь они раскладываются в узлы: строка таблицы и карточка
 * узкого экрана берут одни и те же данные.
 */

import type { ReactNode } from "react";

import type { SectionBoardTask } from "@/shared/api/shopfloor";
import { formatDimensionsLabel } from "@/shared/api/stock";
import { fmtQty } from "@/shared/lib/quantityFormat";
import { TABLE_ROW_STYLES } from "@/shared/lib/tableRowStyles";
import { CutLayoutCell } from "@/shared/ui";
import { taskGroupingDimensions } from "../lib/groupTasksByProfile";
import { getStatusLabel } from "../lib/taskStatus";
import { getStatusDotClass, getTaskTone, taskOperations, taskPackaging, type TaskTone } from "../lib/taskView";

const ROW_TONE_CLASS: Record<TaskTone, string> = {
  waiting: "bg-background hover:bg-slate-50 transition-colors border-l-4 border-l-yellow-400 text-slate-800",
  activeRunning: "bg-amber-50/30 hover:bg-amber-50/70 border-l-4 border-l-amber-400 text-slate-900 font-medium",
  active: "bg-blue-50/20 hover:bg-blue-50/50 border-l-4 border-l-blue-400 text-slate-900",
  completed:
    "bg-emerald-50/10 text-emerald-700/80 line-through decoration-slate-300 hover:bg-emerald-50/30 border-l-4 border-l-emerald-300 opacity-60",
  plain: "",
};

const CARD_TONE_CLASS: Record<TaskTone, string> = {
  waiting: "border border-slate-200 bg-background text-slate-800 rounded-lg border-l-4 border-l-yellow-400",
  activeRunning: "border border-amber-200 bg-amber-50/30 text-slate-900 rounded-lg border-l-4 border-l-amber-400",
  active: "border border-blue-200 bg-blue-50/20 text-slate-900 rounded-lg border-l-4 border-l-blue-400",
  completed:
    "border border-emerald-100 bg-emerald-50/10 text-slate-400 opacity-60 rounded-lg border-l-4 border-l-emerald-300 line-through decoration-slate-300",
  plain: "border border-slate-200 rounded-lg bg-card text-card-foreground",
};

/** Классы строки таблицы: тон задания, а в массовом режиме — выделение. */
export function getTaskRowClass(
  task: SectionBoardTask,
  isSelected: boolean,
  isInGroup: boolean,
): string {
  if (isSelected) return TABLE_ROW_STYLES.selectedRow;
  const toneClass = ROW_TONE_CLASS[getTaskTone(task)];
  if (toneClass) return toneClass;
  return isInGroup ? TABLE_ROW_STYLES.defaultGroupRow : TABLE_ROW_STYLES.defaultRow;
}

/** Классы карточки узкого экрана: тот же тон задания, что и у строки. */
export function getTaskCardClass(task: SectionBoardTask, isSelected: boolean): string {
  if (isSelected) return TABLE_ROW_STYLES.selectedMobileCard;
  return CARD_TONE_CLASS[getTaskTone(task)];
}

/** Точка статуса задания — одна на доску и карточку. */
export function TaskStatusDot({ task }: { task: SectionBoardTask }) {
  return (
    <span
      className={`inline-block h-2.5 w-2.5 rounded-full ${getStatusDotClass(task)}`}
      title={getStatusLabel(task)}
    />
  );
}

export type TaskViewFieldKey =
  | "dimensions"
  | "operation"
  | "packaging"
  | "planned"
  | "issued"
  | "completed"
  | "rejected"
  | "transferred"
  | "remaining";

export type TaskViewField = {
  key: TaskViewFieldKey;
  /** Подпись поля: в строке она живёт в шапке таблицы, в карточке — рядом со значением. */
  label: string;
  node: ReactNode;
  /** Классы ячейки строки; карточка их игнорирует. */
  cellClass?: string;
};

/**
 * Поля задания в порядке колонок доски. Строка разворачивает список в ячейки,
 * карточка — в подписи со значениями, поэтому новое поле добавляется здесь
 * одно, а не в двух раскладках.
 *
 * `hasPackaging` — есть ли у участка упаковочные операции (`Section.has_packaging`).
 * Поле «Упаковка» живёт здесь наравне с колонкой доски (`requiresPackaging` в
 * `boardColumns.ts`) и прячется тем же признаком: шапка без ячейки разъехалась
 * бы с телом строки. Флага нет (`undefined`) — поле остаётся: ошибка
 * справочника не должна прятать данные.
 */
export function buildTaskViewFields(
  task: SectionBoardTask,
  hasPackaging?: boolean,
): TaskViewField[] {
  const fields: TaskViewField[] = [
    {
      key: "dimensions",
      label: "Размер",
      node: formatDimensionsLabel(taskGroupingDimensions(task)),
      cellClass: "text-xs text-muted-foreground",
    },
    {
      key: "operation",
      label: "Операция",
      // Трансформирующий этап (ADR-0002, пила) несёт в ячейке размеры —
      // вход и выходы раскроя (ADR-0058). Нетрансформирующая строка оставляет
      // операции участка списком: на анодировании это цвет, он и есть операция
      // участка, а упаковку несёт своя колонка.
      node: task.transforms_dimensions ? (
        <span className="text-xs">
          <CutLayoutCell
            layout={task.cut_layout}
            fallback={formatDimensionsLabel(taskGroupingDimensions(task))}
          />
        </span>
      ) : (
        <span className="text-xs">{taskOperations(task).join(" · ") || "—"}</span>
      ),
    },
    {
      key: "packaging",
      label: "Упаковка",
      node: <span className="text-xs">{taskPackaging(task) ?? "—"}</span>,
    },
    { key: "planned", label: "План", node: fmtQty(task.planned_quantity) },
    { key: "issued", label: "Выдано", node: fmtQty(task.cache.issued_quantity) },
    { key: "completed", label: "Годные", node: fmtQty(task.cache.completed_quantity) },
    { key: "rejected", label: "Брак", node: fmtQty(task.cache.rejected_quantity) },
    { key: "transferred", label: "Передано", node: fmtQty(task.cache.transferred_quantity) },
    { key: "remaining", label: "Остаток", node: fmtQty(task.cache.remaining_quantity) },
  ];
  return hasPackaging === false
    ? fields.filter((field) => field.key !== "packaging")
    : fields;
}
