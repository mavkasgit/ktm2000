/**
 * lib/boardGroupView.ts — групповое состояние строки-шапки доски.
 *
 * Шапка группы нужна двум раскладкам одной доски (#345): десктопной таблице и
 * телефонной. Пока каждая складывала количества и причины у себя, суммы
 * расходились — шапка таблицы считала `parseFloat`-ом, а разбор ввода —
 * `toQtyInteger` (ревью #283 п. 2): плейсхолдер «сейчас 3» при записанных 2
 * отправлял оператора в цель, которую сервер отвергнет.
 *
 * Здесь группа описывается один раз: суммы по колонкам, записанный факт (через
 * `groupRecordedFact` — ту же базу, что видит разбор ввода), число доводимых
 * строк и причина недоступности завершения. Раскладки только печатают.
 */

import type { SectionBoardTask, TaskGroup } from "@/shared/api/shopfloor";
import type { ActionReasonCode } from "@/shared/lib/actionReasons";
import { toQtyInteger } from "@/shared/lib/quantityFormat";

import { groupRecordedFact } from "./bulkDraft";
import { getTaskGroupHeaderState } from "./taskView";
import { getCompletionBlockReason } from "./taskStatus";

export type TaskGroupView = {
  /** Первая строка группы: артикул, размер и операции шапки. */
  firstTask: SectionBoardTask;
  taskCount: number;
  planQty: number;
  issuedQty: number;
  /** Записанный факт: «Годные» и «Брак» группы, база разбора ввода. */
  goodQty: number;
  defectQty: number;
  transferredQty: number;
  remainingQty: number;
  /** Сколько строк группы можно завершить (ожидающие и закрытые — нет). */
  completableCount: number;
  /** Причина недоступности «Завершить группу»; `null` — кнопка доступна. */
  completeReason: ActionReasonCode | null;
  isCollapsed: boolean;
  allSelected: boolean;
  collapseTitle: string;
};

export type TaskGroupViewOptions = {
  isCollapsed: boolean;
  isBulkMode: boolean;
  allSelected: boolean;
};

/**
 * Сумма количества по строкам группы. Разбор — `toQtyInteger`, как у
 * записанного факта и раскладки ввода: `parseFloat` на пустой строке давал
 * `NaN` («—» в ячейке), а на дроби — сумму, которой нет в данных.
 */
function sumCache(
  tasks: SectionBoardTask[],
  read: (task: SectionBoardTask) => string,
): number {
  return tasks.reduce((sum, task) => sum + toQtyInteger(read(task)), 0);
}

/**
 * Состояние шапки группы. Свёрнутость, выделение и подпись шеврона приходят из
 * `getTaskGroupHeaderState` (одно правило на обе раскладки); суммы и причина
 * завершения считаются здесь, чтобы разметка ничего не складывала сама.
 */
export function buildTaskGroupView(
  group: Pick<TaskGroup, "tasks">,
  options: TaskGroupViewOptions,
): TaskGroupView {
  const { tasks } = group;
  const header = getTaskGroupHeaderState(group, options);
  const completableCount = tasks.filter((task) => getCompletionBlockReason(task) === null).length;

  return {
    firstTask: tasks[0],
    taskCount: tasks.length,
    planQty: sumCache(tasks, (task) => task.planned_quantity),
    issuedQty: sumCache(tasks, (task) => task.cache.issued_quantity),
    goodQty: groupRecordedFact(tasks, "good"),
    defectQty: groupRecordedFact(tasks, "defect"),
    transferredQty: sumCache(tasks, (task) => task.cache.transferred_quantity),
    remainingQty: sumCache(tasks, (task) => task.cache.remaining_quantity),
    completableCount,
    // «Завершить группу» доступна, пока в группе есть хоть одно завершаемое
    // задание: остальные уйдут в пропущенные, и диалог их перечислит.
    completeReason: completableCount > 0 ? null : getCompletionBlockReason(tasks[0]),
    isCollapsed: header.isCollapsed,
    allSelected: header.allSelected,
    collapseTitle: header.collapseTitle,
  };
}
