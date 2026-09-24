import type { DailyPlanCompositionItem, SectionBoardTask } from "@/shared/api/shopfloor";

const TERMINAL_TASK_STATUSES: Record<string, true> = {
  completed: true,
  cancelled: true,
  done: true,
};

export function getDailyPlanCreationCandidates(tasks: SectionBoardTask[]): SectionBoardTask[] {
  return tasks.filter((task) => !TERMINAL_TASK_STATUSES[task.status]);
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
