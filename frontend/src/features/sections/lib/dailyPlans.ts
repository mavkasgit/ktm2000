import type { DailyPlanCompositionItem, SectionBoardTask } from "@/shared/api/shopfloor";
import { getTaskViewCategory } from "./taskStatus";

/**
 * Актуальные задания участка — те, из которых собирается новый план. Два
 * среза отсекаются:
 *
 * — завершённые: терминальный статус, полное выполнение или полная передача.
 *   Иначе вкладка «План» без выбранного плана показывала бы строки
 *   «Завершен», которых нет на вкладке «Задания», а сервер всё равно отказал бы
 *   во включении их в план (closed status);
 * — уже включённые в какой-либо дневной план (#301): по прямому членству,
 *   без оглядки на то, показывается ли задание в составе плана. Скрытие
 *   полное — без строки-заменителя и без пояснений: задание и так видно в
 *   списке планов участка.
 *
 * Без признака `in_daily_plan` (старый ответ доски) поведение прежнее.
 */
export function getDailyPlanCreationCandidates(tasks: SectionBoardTask[]): SectionBoardTask[] {
  return tasks.filter(
    (task) => task.in_daily_plan !== true && getTaskViewCategory(task) !== "completed",
  );
}

export function mergeDailyPlanTasks(compositions: DailyPlanCompositionItem[][]): SectionBoardTask[] {
  const tasksById = new Map<number, SectionBoardTask>();
  for (const composition of compositions) {
    for (const item of composition) {
      if (!tasksById.has(item.work_task_id)) {
        tasksById.set(item.work_task_id, item.task);
      }
    }
  }
  return [...tasksById.values()];
}
