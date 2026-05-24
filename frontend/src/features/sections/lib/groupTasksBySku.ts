import type { SectionBoardTask } from "@/shared/api/shopfloor";

export type TaskGroup = {
  groupKey: string;
  productSku: string;
  routeStepId: number;
  sequence: number;
  operationName: string | null;
  tasks: SectionBoardTask[];
  isGroup: true;
};

export type SingleTask = {
  task: SectionBoardTask;
  isGroup: false;
};

export type BoardRowItem = TaskGroup | SingleTask;

function makeGroupKey(productSku: string, routeStepId: number): string {
  return `${productSku}__${routeStepId}`;
}

function sumCacheField(tasks: SectionBoardTask[], field: keyof SectionBoardTask["cache"]): number {
  let total = 0;
  for (const t of tasks) {
    const v = parseFloat(t.cache[field]);
    if (Number.isFinite(v)) total += v;
  }
  return total;
}

export function getGroupAggregates(group: TaskGroup) {
  const tasks = group.tasks;
  return {
    plannedQty: sumCacheField(tasks, "completed_quantity") > 0
      ? sumCacheField(tasks, "completed_quantity")
      : sumCacheField(tasks, "in_work_quantity") > 0
        ? sumCacheField(tasks, "in_work_quantity")
        : parseFloat(tasks[0].planned_quantity) || 0,
    issuedQty: sumCacheField(tasks, "issued_quantity"),
    inWorkQty: sumCacheField(tasks, "in_work_quantity"),
    completedQty: sumCacheField(tasks, "completed_quantity"),
    rejectedQty: sumCacheField(tasks, "rejected_quantity"),
    transferredQty: sumCacheField(tasks, "transferred_quantity"),
    remainingQty: sumCacheField(tasks, "remaining_quantity"),
    taskIds: tasks.map((t) => t.id),
  };
}

export function groupTasksBySku(tasks: SectionBoardTask[]): BoardRowItem[] {
  const map = new Map<string, SectionBoardTask[]>();

  for (const task of tasks) {
    const key = makeGroupKey(task.product_sku, task.route_step_id);
    const existing = map.get(key);
    if (existing) {
      existing.push(task);
    } else {
      map.set(key, [task]);
    }
  }

  const items: BoardRowItem[] = [];

  for (const [key, groupTasks] of map) {
    if (groupTasks.length >= 2) {
      const sorted = [...groupTasks].sort((a, b) => a.id - b.id);
      items.push({
        groupKey: key,
        productSku: sorted[0].product_sku,
        routeStepId: sorted[0].route_step_id,
        sequence: sorted[0].sequence,
        operationName: sorted[0].operation_name,
        tasks: sorted,
        isGroup: true,
      });
    } else {
      items.push({
        task: groupTasks[0],
        isGroup: false,
      });
    }
  }

  items.sort((a, b) => {
    const seqA = a.isGroup ? a.sequence : a.task.sequence;
    const seqB = b.isGroup ? b.sequence : b.task.sequence;
    return seqA - seqB;
  });

  return items;
}
