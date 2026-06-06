/**
 * lib/bulkOperations.ts
 * ======================
 * Чистые функции для группового завершения на доске участка.
 * Вынесены из BulkOperationsPanel.tsx для unit-тестирования.
 */

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
  // Группа-уровень inputs
  addQty: string;
  defectQty: string;
  confirmed: boolean;
  // Per-task распределение (для submit)
  taskAddQty: Record<number, number>;
  taskDefectQty: Record<number, number>;
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

function distributeQtyUncapped(
  tasks: MockTask[],
  totalQty: number,
): Record<number, number> {
  const result: Record<number, number> = {};
  let remaining = totalQty;
  for (const task of tasks) {
    if (remaining <= 0) {
      result[task.id] = 0;
      continue;
    }
    result[task.id] = remaining;
    remaining = 0;
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

  // Дефолт для «+ Добавить» = 0 (пользователь сам вводит)
  const defaultAddQty = "0";
  const defaultDefectQty = "0";

  const taskAddQty: Record<number, number> = {};
  for (const task of tasks) taskAddQty[task.id] = 0;
  const taskDefectQty: Record<number, number> = {};
  for (const task of tasks) taskDefectQty[task.id] = 0;

  return {
    key, tasks, label, operationName,
    totalPlan, totalIssued, totalInWork, totalCompleted, totalTransferred, totalRejected, totalRemaining,
    addQty: defaultAddQty, defectQty: defaultDefectQty,
    confirmed: false,
    taskAddQty, taskDefectQty,
  };
}

export function distributeAddAndDefect(group: BulkOpGroup): BulkOpGroup {
  const addVal = toInteger(group.addQty);
  const defectVal = toInteger(group.defectQty);
  return {
    ...group,
    taskAddQty: distributeQtyUncapped(group.tasks, addVal),
    taskDefectQty: distributeQtyUncapped(group.tasks, defectVal),
  };
}

export function getTaskProgress(group: BulkOpGroup): string {
  return group.tasks.map((task) => {
    const completed = toInteger(task.cache.completed_quantity);
    const planned = toInteger(task.planned_quantity);
    return `${completed}/${planned}`;
  }).join(", ");
}
