import type { RouteHistoryOp, SectionBoardTask } from "@/shared/api/shopfloor";
import { formatDimensionsLabel } from "@/shared/api/stock";
import { colorNameLabels } from "@/shared/lib/generated-labels";
import { taskGroupingDimensions } from "./groupTasksByProfile";
import { taskPackaging } from "./taskView";

/** Режим верхней группировки строк плана анодирования. */
export type PlanTaskGroupingMode = "article" | "anodizingColor";

export type PlanTaskRow = {
  key: string;
  groupKey: string;
  /** Задания строки: операции совпадают, упаковка может различаться. */
  tasks: SectionBoardTask[];
  productSku: string;
  dimensions: Record<string, unknown> | null;
  color: string | null;
  preOperations: RouteHistoryOp[];
  operationName: string;
  /** Упаковка строки: операция участка и количество, planQty вклада задания. */
  packaging: { label: string; qty: number }[];
  planQty: number;
  issuedQty: number;
  doneQty: number;
  transferredQty: number;
  balanceQty: number;
};

export type PlanTaskGroup = {
  key: string;
  label: string;
  rows: PlanTaskRow[];
  totalQtyPlan: number;
  totalQtyDone: number;
  totalQtyIssued: number;
  totalQtyTransferred: number;
};

function toNumber(value: string | number | null | undefined): number {
  const number = typeof value === "number" ? value : Number(value ?? 0);
  return Number.isFinite(number) ? number : 0;
}

function dimensionsKey(task: SectionBoardTask): string {
  const dimensions = taskGroupingDimensions(task);
  if (!dimensions) return "__no_dimensions__";
  return Object.keys(dimensions)
    .sort()
    .map((key) => `${key}=${String(dimensions[key])}`)
    .join("|");
}

function taskColor(task: SectionBoardTask): string | null {
  const payloadColor = task.source_payload?.color;
  if (typeof payloadColor === "string" && payloadColor.trim()) return payloadColor.trim();

  const outputKind = task.output_kind;
  if (outputKind && colorNameLabels[outputKind]) return outputKind;
  return null;
}


function groupKeyForTask(task: SectionBoardTask, mode: PlanTaskGroupingMode): string {
  const size = dimensionsKey(task);
  return mode === "article"
    ? `${task.product_sku}__${size}`
    : `${taskColor(task) ?? "__no_color__"}__${size}`;
}

function groupLabelForTask(task: SectionBoardTask, mode: PlanTaskGroupingMode): string {
  const color = taskColor(task);
  const colorLabel = color ? colorNameLabels[color] ?? color : "Без цвета";
  const size = formatDimensionsLabel(taskGroupingDimensions(task));
  return mode === "article"
    ? `${task.product_sku} · ${size}`
    : `${colorLabel} · ${size}`;
}

/** Подпись строки: задания сливаются, только если совпадает всё, что в колонках. */
function rowSignature(task: SectionBoardTask, preOperations: RouteHistoryOp[]): string {
  const operations = preOperations
    .map((operation) => operation.operation_name)
    .filter(Boolean)
    .join(" → ");
  return [
    task.product_sku,
    taskColor(task) ?? "__no_color__",
    dimensionsKey(task),
    operations,
    task.operation_name ?? "",
  ].join("__");
}

function makeRow(
  task: SectionBoardTask,
  groupKey: string,
  preOperations: RouteHistoryOp[],
): PlanTaskRow {
  const planned = toNumber(task.planned_quantity);
  const packaging = taskPackaging(task);

  return {
    key: `${groupKey}__task_${task.id}`,
    groupKey,
    tasks: [task],
    productSku: task.product_sku,
    dimensions: taskGroupingDimensions(task),
    color: taskColor(task),
    preOperations,
    operationName: task.operation_name || "Операция",
    packaging: packaging ? [{ label: packaging, qty: planned }] : [],
    planQty: planned,
    issuedQty: toNumber(task.cache.issued_quantity),
    doneQty: toNumber(task.cache.completed_quantity),
    transferredQty: toNumber(task.cache.transferred_quantity),
    balanceQty: 0,
  };
}

/** Доливает строку плана заданием: количества суммируются, упаковка — в разбивку. */
function mergeTaskIntoRow(row: PlanTaskRow, task: SectionBoardTask): void {
  const planned = toNumber(task.planned_quantity);
  const packaging = taskPackaging(task);

  row.tasks.push(task);
  if (packaging) {
    const existing = row.packaging.find((item) => item.label === packaging);
    if (existing) existing.qty += planned;
    else row.packaging.push({ label: packaging, qty: planned });
  }
  row.planQty += planned;
  row.issuedQty += toNumber(task.cache.issued_quantity);
  row.doneQty += toNumber(task.cache.completed_quantity);
  row.transferredQty += toNumber(task.cache.transferred_quantity);
}

function sortPackaging(row: PlanTaskRow): void {
  row.packaging.sort((a, b) => b.qty - a.qty || a.label.localeCompare(b.label, "ru"));
}

function sumRows(rows: PlanTaskRow[], field: "planQty" | "issuedQty" | "doneQty" | "transferredQty"): number {
  return rows.reduce((total, row) => total + row[field], 0);
}

/**
 * Строит дерево плана: верхняя группа — артикул или цвет анодирования,
 * внутри — одна строка на набор заданий с одинаковыми операциями. Задания,
 * отличающиеся только упаковкой, сливаются в строку: количество и подвесы
 * общие, упаковка показана разбивкой «Спанбонд 300 · Стрейч 200».
 */
export function buildPlanTaskGroups(
  tasks: SectionBoardTask[],
  mode: PlanTaskGroupingMode,
): PlanTaskGroup[] {
  const groups = new Map<string, { key: string; label: string; rows: PlanTaskRow[] }>();
  const rowsByGroup = new Map<string, Map<string, PlanTaskRow>>();

  for (const task of tasks) {
    const key = groupKeyForTask(task, mode);
    const preOperations = (task.route_history ?? []).filter((operation) => operation.is_significant);
    const signature = rowSignature(task, preOperations);

    let rows = rowsByGroup.get(key);
    if (!rows) {
      rows = new Map<string, PlanTaskRow>();
      rowsByGroup.set(key, rows);
    }

    const existingRow = rows.get(signature);
    if (existingRow) {
      mergeTaskIntoRow(existingRow, task);
      continue;
    }

    const row = makeRow(task, key, preOperations);
    rows.set(signature, row);

    const group = groups.get(key);
    if (group) {
      group.rows.push(row);
    } else {
      groups.set(key, { key, label: groupLabelForTask(task, mode), rows: [row] });
    }
  }

  for (const group of groups.values()) {
    for (const row of group.rows) {
      row.balanceQty = Math.max(0, row.planQty - row.doneQty);
      sortPackaging(row);
    }
  }

  // Итоги группы — сумма по строкам: слитые задания уже учтены в своих строках.
  return Array.from(groups.values())
    .map((group): PlanTaskGroup => ({
      key: group.key,
      label: group.label,
      rows: group.rows,
      totalQtyPlan: sumRows(group.rows, "planQty"),
      totalQtyDone: sumRows(group.rows, "doneQty"),
      totalQtyIssued: sumRows(group.rows, "issuedQty"),
      totalQtyTransferred: sumRows(group.rows, "transferredQty"),
    }))
    .sort((a, b) => {
      if (b.totalQtyPlan !== a.totalQtyPlan) return b.totalQtyPlan - a.totalQtyPlan;
      return a.label.localeCompare(b.label, "ru");
    });
}
