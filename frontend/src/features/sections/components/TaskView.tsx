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
import { getGroupTone, getStatusDotClass, getTaskTone, taskOperations, taskPackaging, type TaskTone } from "../lib/taskView";

/**
 * Тон задания разложен на части: заливка, полоса и текст. Части собираются
 * по-разному для строки вне группы и для строки раскрытой группы, а
 * разложить их одним классом нельзя — тогда фон строки спорит с фоном блока.
 */
const TONE_WASH_CLASS: Record<TaskTone, string> = {
  waiting: "bg-background hover:bg-slate-50",
  activeRunning: "bg-amber-50/30 hover:bg-amber-50/70",
  active: "bg-blue-50/20 hover:bg-blue-50/50",
  completed: "bg-emerald-50/10 hover:bg-emerald-50/30",
  plain: "",
};

/**
 * Полоса статуса — 4px у левого края первой ячейки. Живёт на ячейке, а не на
 * `<tr>`: таблица доски объявлена `border-separate`, и границы строк в ней не
 * рисуются вовсе (проверено пиксельно) — прежние полосы на `<tr>` не были видны.
 * Полоса есть у всех тонов, у «обычного» — прозрачная: без неё ячейка шире на
 * 4px, и точка статуса уезжала бы вбок у каждой второй строки.
 */
const TONE_STRIPE_CLASS: Record<TaskTone, string> = {
  waiting: "border-l-4 border-l-yellow-400",
  activeRunning: "border-l-4 border-l-amber-400",
  active: "border-l-4 border-l-blue-400",
  completed: "border-l-4 border-l-emerald-300",
  plain: TABLE_ROW_STYLES.emptyRail,
};

const TONE_TEXT_CLASS: Record<TaskTone, string> = {
  waiting: "text-slate-800 dark:text-slate-200",
  activeRunning: "text-slate-900 dark:text-slate-100 font-medium",
  active: "text-slate-900 dark:text-slate-100",
  completed:
    "text-emerald-700/80 dark:text-emerald-300/70 line-through decoration-slate-300 opacity-60",
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

/**
 * Рельс шапки группы — тот же левый край, что у строк блока (4px), поэтому
 * шапка и её строки читаются одним куском. Цвет — тон группы, а не первой её
 * строки: блок показывает состояние, но фоном не подменяет статус строк
 * (на фоне подменялись статусные пилюли).
 */
const GROUP_RAIL_CLASS: Record<TaskTone, string> = {
  waiting: "border-l-4 border-l-yellow-400",
  activeRunning: "border-l-4 border-l-amber-400",
  active: "border-l-4 border-l-blue-400",
  completed: "border-l-4 border-l-emerald-300",
  plain: "border-l-4 border-l-slate-300 dark:border-l-slate-600",
};

/** Рельс шапки группы: цвет — по состоянию группы, а не по первой её строке. */
export function getTaskGroupRailClass(tasks: SectionBoardTask[]): string {
  return GROUP_RAIL_CLASS[getGroupTone(tasks)];
}

/** Полоса статуса строки — на первую ячейку строки. */
export function getTaskStripeClass(task: SectionBoardTask): string {
  return TONE_STRIPE_CLASS[getTaskTone(task)];
}

/** Классы строки таблицы: тон задания, а в массовом режиме — выделение. */
export function getTaskRowClass(
  task: SectionBoardTask,
  isSelected: boolean,
  isInGroup: boolean,
): string {
  if (isSelected) return TABLE_ROW_STYLES.selectedRow;
  const tone = getTaskTone(task);
  // Строка раскрытой группы: подложка одна на блок (её же носит шапка), поэтому
  // «чей это статус» несут только полоса слева и текст. Свой тон строки остаётся,
  // но полосой и цветом текста, а не фоном: цветной фон строки делал пилюлю
  // статуса неразличимой и распадал блок на отдельные строки.
  if (isInGroup) {
    return `${TABLE_ROW_STYLES.groupBlock} ${TONE_TEXT_CLASS[tone]} transition-colors`;
  }
  const wash = TONE_WASH_CLASS[tone];
  return wash ? `${wash} ${TONE_TEXT_CLASS[tone]} transition-colors` : TABLE_ROW_STYLES.defaultRow;
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
