import type { RouteHistoryOp, SectionBoardTask } from "@/shared/api/shopfloor";
import { formatDimensionsLabel } from "@/shared/api/stock";
import { colorNameLabels } from "@/shared/lib/generated-labels";
import { taskGroupingDimensions } from "./groupTasksByProfile";

/** Режим верхней группировки строк плана анодирования. */
export type PlanTaskGroupingMode = "article" | "anodizingColor";

export type PlanTaskRow = {
  key: string;
  groupKey: string;
  task: SectionBoardTask;
  dimensions: Record<string, unknown> | null;
  color: string | null;
  preOperations: RouteHistoryOp[];
  packaging: string | null;
  packagingDetails: string[];
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

function taskPackaging(task: SectionBoardTask): { label: string | null; details: string[] } {
  const payload = task.source_payload ?? {};
  const rawLabel = payload.packaging;
  const label = typeof rawLabel === "string" && rawLabel.trim() ? rawLabel.trim() : null;
  const details: string[] = [];

  const packagedIn18 = payload.packaging_1_8_quantity;
  if (packagedIn18 !== null && packagedIn18 !== undefined && String(packagedIn18).trim() !== "") {
    details.push(`1,8 м: ${String(packagedIn18)}`);
  }
  const added = payload.add_quantity;
  if (added !== null && added !== undefined && String(added).trim() !== "") {
    details.push(`Добавить: ${String(added)}`);
  }

  return { label, details };
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

function makeRow(task: SectionBoardTask, groupKey: string): PlanTaskRow {
  const planned = toNumber(task.planned_quantity);
  const issued = toNumber(task.cache.issued_quantity);
  const done = toNumber(task.cache.completed_quantity);
  const transferred = toNumber(task.cache.transferred_quantity);
  const packaging = taskPackaging(task);

  return {
    key: `${groupKey}__task_${task.id}`,
    groupKey,
    task,
    dimensions: taskGroupingDimensions(task),
    color: taskColor(task),
    preOperations: (task.route_history ?? []).filter((operation) => operation.is_significant),
    packaging: packaging.label,
    packagingDetails: packaging.details,
    planQty: planned,
    issuedQty: issued,
    doneQty: done,
    transferredQty: transferred,
    balanceQty: Math.max(0, planned - done),
  };
}

/**
 * Строит дерево плана: верхняя группа — артикул или цвет анодирования,
 * внутри — одна строка на задание. Упаковка остаётся данными этой строки,
 * а не отдельным уровнем группировки.
 */
export function buildPlanTaskGroups(
  tasks: SectionBoardTask[],
  mode: PlanTaskGroupingMode,
): PlanTaskGroup[] {
  const groups = new Map<string, PlanTaskGroup>();

  for (const task of tasks) {
    const key = groupKeyForTask(task, mode);
    const row = makeRow(task, key);
    const existing = groups.get(key);
    if (existing) {
      existing.rows.push(row);
      existing.totalQtyPlan += row.planQty;
      existing.totalQtyDone += row.doneQty;
      existing.totalQtyIssued += row.issuedQty;
      existing.totalQtyTransferred += row.transferredQty;
    } else {
      groups.set(key, {
        key,
        label: groupLabelForTask(task, mode),
        rows: [row],
        totalQtyPlan: row.planQty,
        totalQtyDone: row.doneQty,
        totalQtyIssued: row.issuedQty,
        totalQtyTransferred: row.transferredQty,
      });
    }
  }

  return Array.from(groups.values()).sort((a, b) => {
    if (b.totalQtyPlan !== a.totalQtyPlan) return b.totalQtyPlan - a.totalQtyPlan;
    return a.label.localeCompare(b.label, "ru");
  });
}
