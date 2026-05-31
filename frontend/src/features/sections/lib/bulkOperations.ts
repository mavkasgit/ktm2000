/**
 * lib/bulkOperations.ts
 * ======================
 * Чистые функции для массовых операций на доске участка.
 * Вынесены из BulkOperationsPanel.tsx для unit-тестирования.
 */

export type RowStep = "issue" | "complete" | "send";

export type BulkOpGroup = {
  key: string;
  tasks: MockTask[];
  label: string;
  operationName: string;
  totalPlan: number;
  totalIssued: number;
  totalInWork: number;
  totalCompleted: number;
  totalTransferred: number;
  totalRejected: number;
  totalRemaining: number;
  issueQty: string;
  completeQty: string;
  defectQty: string;
  sendQty: string;
  confirmedSteps: Set<RowStep>;
  taskIssueQty: Record<number, number>;
  taskCompleteQty: Record<number, number>;
  taskDefectQty: Record<number, number>;
  taskSendQty: Record<number, number>;
  issueArrowActive: boolean;
  completeArrowActive: boolean;
};

export type MockTask = {
  id: number;
  product_sku: string;
  operation_name: string;
  operation_code: string | null;
  planned_quantity: string;
  cache: {
    available_quantity: string;
    issued_quantity: string;
    in_work_quantity: string;
    completed_quantity: string;
    transferred_quantity: string;
    rejected_quantity: string;
    remaining_quantity: string;
  };
};

export function toInteger(value: string | number): number {
  const n = typeof value === "number" ? value : parseFloat(value);
  return Number.isFinite(n) ? Math.round(n) : 0;
}

function sumTasks(tasks: MockTask[], getVal: (task: MockTask) => number): number {
  return tasks.reduce((s, t) => s + getVal(t), 0);
}

function distributeQtySequential(
  tasks: MockTask[],
  totalQty: number,
  getMax: (task: MockTask) => number,
): Record<number, number> {
  const result: Record<number, number> = {};
  let remaining = totalQty;
  for (const task of tasks) {
    if (remaining <= 0) {
      result[task.id] = 0;
      continue;
    }
    const max = getMax(task);
    const allocated = Math.min(remaining, max);
    result[task.id] = allocated;
    remaining -= allocated;
  }
  return result;
}

export function initGroup(tasks: MockTask[]): BulkOpGroup {
  const key = `${tasks[0].product_sku}__${tasks[0].operation_code || tasks[0].operation_name || "—"}`;
  const label = tasks[0].product_sku;
  const operationName = tasks[0].operation_name || "—";

  const totalPlan = sumTasks(tasks, (t) => toInteger(t.planned_quantity));
  const totalIssued = sumTasks(tasks, (t) => toInteger(t.cache.issued_quantity));
  const totalInWork = sumTasks(tasks, (t) => toInteger(t.cache.in_work_quantity));
  const totalCompleted = sumTasks(tasks, (t) => toInteger(t.cache.completed_quantity));
  const totalTransferred = sumTasks(tasks, (t) => toInteger(t.cache.transferred_quantity));
  const totalRejected = sumTasks(tasks, (t) => toInteger(t.cache.rejected_quantity));
  const totalRemaining = sumTasks(tasks, (t) => toInteger(t.cache.remaining_quantity));

  const defaultIssueQty = "";
  const defaultCompleteQty = totalCompleted > 0 ? String(totalCompleted) : "0";
  const defaultDefectQty = totalRejected > 0 ? String(totalRejected) : "0";
  const defaultSendQty = totalTransferred > 0 ? String(totalTransferred) : "0";

  const taskIssueQty: Record<number, number> = {};
  for (const task of tasks) taskIssueQty[task.id] = 0;
  const taskCompleteQty = distributeQtySequential(tasks, toInteger(defaultCompleteQty || "0"), (t) => toInteger(t.cache.in_work_quantity));
  const taskSendQty: Record<number, number> = {};
  for (const task of tasks) taskSendQty[task.id] = 0;

  return {
    key, tasks, label, operationName,
    totalPlan, totalIssued, totalInWork, totalCompleted, totalTransferred, totalRejected, totalRemaining,
    issueQty: defaultIssueQty, completeQty: defaultCompleteQty, defectQty: defaultDefectQty, sendQty: defaultSendQty,
    confirmedSteps: new Set<RowStep>(),
    taskIssueQty, taskCompleteQty, taskDefectQty: {}, taskSendQty,
    issueArrowActive: false, completeArrowActive: false,
  };
}

export function activateIssueArrow(group: BulkOpGroup): BulkOpGroup {
  const inputVal = toInteger(group.issueQty);
  const taskCompleteQty: Record<number, number> = {};
  let remainingInput = inputVal;
  for (const task of group.tasks) {
    const taskIssued = toInteger(task.cache.issued_quantity);
    const taskCompleted = toInteger(task.cache.completed_quantity);
    const taskDefect = toInteger(task.cache.rejected_quantity);
    const alreadyInWork = Math.max(0, taskIssued - taskCompleted - taskDefect);
    const taskPlan = toInteger(task.planned_quantity);
    const canAdd = Math.max(0, taskPlan - taskIssued);
    const addFromInput = Math.min(remainingInput, canAdd);
    taskCompleteQty[task.id] = alreadyInWork + addFromInput;
    remainingInput -= addFromInput;
  }
  const totalComplete = Object.values(taskCompleteQty).reduce((s, v) => s + v, 0);
  return {
    ...group,
    completeQty: totalComplete > 0 ? String(totalComplete) : "",
    taskCompleteQty,
    issueArrowActive: true,
  };
}

export function activateCompleteArrow(group: BulkOpGroup): BulkOpGroup {
  const inputCompleteVal = toInteger(group.completeQty);
  const inputDefectVal = toInteger(group.defectQty);
  const taskSendQty: Record<number, number> = {};
  let remainingInput = Math.max(0, inputCompleteVal - inputDefectVal);
  for (const task of group.tasks) {
    const taskCompleted = toInteger(task.cache.completed_quantity);
    const taskTransferred = toInteger(task.cache.transferred_quantity);
    const taskDefect = toInteger(task.cache.rejected_quantity);
    const alreadyCompleted = Math.max(0, taskCompleted - taskTransferred - taskDefect);
    taskSendQty[task.id] = alreadyCompleted;
    remainingInput -= alreadyCompleted;
  }
  if (remainingInput > 0) {
    for (const task of group.tasks) {
      const taskCompleted = toInteger(task.cache.completed_quantity);
      const taskTransferred = toInteger(task.cache.transferred_quantity);
      const taskDefect = toInteger(task.cache.rejected_quantity);
      const sendable = Math.max(0, taskCompleted - taskTransferred - taskDefect);
      const currentAlloc = taskSendQty[task.id] || 0;
      const canAdd = Math.max(0, sendable - currentAlloc);
      const add = Math.min(remainingInput, canAdd);
      taskSendQty[task.id] = currentAlloc + add;
      remainingInput -= add;
      if (remainingInput <= 0) break;
    }
  }
  const totalSend = Object.values(taskSendQty).reduce((s, v) => s + v, 0);
  return {
    ...group,
    sendQty: totalSend > 0 ? String(totalSend) : "",
    taskSendQty,
    completeArrowActive: true,
  };
}

export function getTaskProgress(group: BulkOpGroup): string {
  return group.tasks.map((task) => {
    const transferred = toInteger(task.cache.transferred_quantity);
    const planned = toInteger(task.planned_quantity);
    return `${transferred}/${planned}`;
  }).join(", ");
}
