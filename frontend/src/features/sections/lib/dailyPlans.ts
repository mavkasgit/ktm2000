import type { DailyPlanCompositionItem, SectionBoardTask } from "@/shared/api/shopfloor";
import { getTaskViewCategory } from "./taskStatus";

/**
 * Актуальные задания участка — те, из которых собирается план. Признак тот же,
 * что у категории «Завершенные» на доске: терминальный статус, полное
 * выполнение или полная передача. Иначе вкладка «План» без выбранного плана
 * показывала бы строки «Завершен», которых нет на вкладке «Задания», а сервер
 * всё равно отказал бы во включении их в план (closed status).
 */
export function getDailyPlanCreationCandidates(tasks: SectionBoardTask[]): SectionBoardTask[] {
  return tasks.filter((task) => getTaskViewCategory(task) !== "completed");
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
