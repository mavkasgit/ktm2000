import type { DailyPlanCompositionItem, SectionBoardTask } from "@/shared/api/shopfloor";
import { getTaskViewCategory } from "./taskStatus";

/**
 * Актуальные задания участка — то, что показывает вкладка «План» без
 * выбранного плана. Режется один срез: завершённые строки видны только в
 * составе конкретного плана (docs/daily-plans-spec.md, «Режим `План`»), и
 * сервер всё равно отказал бы включить их в новый план.
 *
 * Занятые планом задания здесь остаются: режим просмотра — это картина
 * участка, а не набор кандидатов (#301). Прячет их только режим создания —
 * `getDailyPlanCreationCandidates`.
 */
export function getCurrentSectionTasks(tasks: SectionBoardTask[]): SectionBoardTask[] {
  return tasks.filter((task) => getTaskViewCategory(task) !== "completed");
}

/**
 * Кандидаты нового дневного плана. Два среза:
 *
 * — завершённые: терминальный статус, полное выполнение или полная передача;
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
