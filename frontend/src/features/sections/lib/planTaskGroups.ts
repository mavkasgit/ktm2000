import type { RouteHistoryOp, SectionBoardTask } from "@/shared/api/shopfloor";
import type { ProductPairCatalogEntry } from "@/shared/api/products";
import { formatDimensionsLabel } from "@/shared/api/stock";
import { clusterByArticle } from "@/shared/lib/clusterByArticle";
import { lengthKey } from "@/shared/lib/hangerQuantity";
import { outputKindLabels } from "@/shared/lib/generated-labels";
import { taskGroupingDimensions } from "./groupTasksByProfile";
import { taskPackaging } from "./taskView";

/**
 * Пара, в которую входит артикул, и её норма на подвес для конкретной длины.
 *
 * После снятия склейки (#312) пара — это две независимые позиции, поэтому
 * на печати их нужно снова свести вместе: обе строки печатаются одним
 * подвесом с обоими артикулами. Источник — каталог пар `/product-pairs`,
 * тот же, что у витрины расчёта подвесов.
 */
export type PlanPairIndex = Map<number, ProductPairCatalogEntry>;

/** Индекс пар по ``product_id`` артикула: обе позиции пары попадают в один ключ. */
export function buildPlanPairIndex(pairs: ProductPairCatalogEntry[]): PlanPairIndex {
  const index: PlanPairIndex = new Map();
  for (const pair of pairs) {
    index.set(Number(pair.product_a_id), pair);
    index.set(Number(pair.product_b_id), pair);
  }
  return index;
}

/**
 * Норма пары на длине строки: ручное значение пары приоритетнее авто,
 * иначе берётся авто. Нет ни того, ни другого — нормы нет.
 */
function pairQuantityPerHanger(pair: ProductPairCatalogEntry, lengthMm: number | null): number | null {
  if (lengthMm == null) return null;
  const entry = pair.quantity_per_hanger?.[lengthKey(lengthMm)];
  if (!entry) return null;
  if (typeof entry.manual === "number" && entry.manual > 0) return entry.manual;
  if (typeof entry.auto === "number" && entry.auto > 0) return entry.auto;
  return null;
}

function taskLengthMm(task: SectionBoardTask): number | null {
  const length = taskGroupingDimensions(task)?.length_mm;
  return typeof length === "number" && length > 0 ? length : null;
}

/** Пара задания по его артикулу; `null` — артикул непарный или каталог не загружен. */
function taskPair(task: SectionBoardTask, pairs: PlanPairIndex | undefined): ProductPairCatalogEntry | null {
  if (!pairs) return null;
  return pairs.get(Number(task.product_id)) ?? null;
}

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
  /** Пара, если группа собрана из двух позиций одного подвеса (#312). */
  pair: PlanTaskGroupPair | null;
};

/**
 * Подвес пары: обе позиции печатаются вместе, поэтому у группы одна норма
 * и один счёт подвесов, а не сумма по артикулам.
 */
export type PlanTaskGroupPair = {
  id: number;
  /** SKU компонентов пары — строки группы. */
  skus: string[];
  /** Норма пары на длине группы; `null` — норма не задана. */
  quantityPerHanger: number | null;
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

/**
 * Цвет приходит каноническим русским словом из `payload.color`, поэтому здесь
 * нечего переводить. Запасной путь — `output_kind` — берётся только когда там
 * не вид выпуска (`ГП`/`П/ф`): это прежнее поведение, просто словарь цветов
 * уехал в канон имёнем значения.
 */
function taskColor(task: SectionBoardTask): string | null {
  const payloadColor = task.source_payload?.color;
  if (typeof payloadColor === "string" && payloadColor.trim()) return payloadColor.trim();

  const outputKind = task.output_kind;
  if (outputKind && !outputKindLabels[outputKind]) return outputKind;
  return null;
}


/**
 * Ключ верхней группы. Режим ``article`` у парных строк ключуется по паре,
 * а не по своему артикулу: обе позиции печатаются одним подвесом, поэтому
 * они обязаны попасть в одну группу, иначе на подвес уедут две строки с
 * половинной нормой (#312). Артикул при этом остаётся в подписи строки —
 * работа идёт по каждому артикулу отдельно.
 */
function groupKeyForTask(
  task: SectionBoardTask,
  mode: PlanTaskGroupingMode,
  pairs: PlanPairIndex | undefined,
): string {
  const size = dimensionsKey(task);
  if (mode === "anodizingColor") {
    return `${taskColor(task) ?? "__no_color__"}__${size}`;
  }
  const pair = taskPair(task, pairs);
  return pair ? `pair_${pair.id}__${size}` : `${task.product_sku}__${size}`;
}

/**
 * SKU заданий пары — по ключу группы (пара + размер), а не по паре целиком:
 * артикулы одной пары на разных длинах печатаются разными подвесами, и в
 * подписи должен быть тот состав, который реально на листе.
 */
function pairSkusForGroup(
  tasks: SectionBoardTask[],
  pairs: PlanPairIndex | undefined,
): Map<string, Set<string>> {
  const byGroup = new Map<string, Set<string>>();
  if (!pairs) return byGroup;
  for (const task of tasks) {
    const key = groupKeyForTask(task, "article", pairs);
    const skus = byGroup.get(key) ?? new Set<string>();
    skus.add(task.product_sku);
    byGroup.set(key, skus);
  }
  return byGroup;
}

/**
 * Подпись группы: пара подписывается теми артикулами, что есть на листе, —
 * «A+B · размер». Одиночная позиция пары подписывается своим артикулом.
 */
function groupLabelForTask(
  task: SectionBoardTask,
  mode: PlanTaskGroupingMode,
  pairs: PlanPairIndex | undefined,
  pairSkus: Map<string, Set<string>>,
): string {
  const size = formatDimensionsLabel(taskGroupingDimensions(task));
  if (mode === "anodizingColor") {
    return `${taskColor(task) ?? "Без цвета"} · ${size}`;
  }
  const key = groupKeyForTask(task, "article", pairs);
  const skus = Array.from(pairSkus.get(key) ?? []).sort();
  return skus.length > 1 ? `${skus.join("+")} · ${size}` : `${task.product_sku} · ${size}`;
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
 * Строит дерево плана: верхняя группа — артикул, цвет анодирования или пара,
 * внутри — одна строка на набор заданий с одинаковыми операциями. Задания,
 * отличающиеся только упаковкой, сливаются в строку: количество и подвесы
 * общие, упаковка показана разбивкой «Спанбонд 300 · Стрейч 200».
 *
 * `pairs` — индекс пар по `product_id` (#312). В режиме ``article`` строки
 * одной пары попадают в одну группу с общей нормой подвеса: работа при этом
 * идёт по каждой позиции отдельно, строки не сливаются.
 */
export function buildPlanTaskGroups(
  tasks: SectionBoardTask[],
  mode: PlanTaskGroupingMode,
  pairs?: PlanPairIndex,
): PlanTaskGroup[] {
  const pairSkus = pairSkusForGroup(tasks, pairs);
  const groups = new Map<string, { key: string; label: string; rows: PlanTaskRow[]; pair: ProductPairCatalogEntry | null }>();
  const rowsByGroup = new Map<string, Map<string, PlanTaskRow>>();

  for (const task of tasks) {
    const key = groupKeyForTask(task, mode, pairs);
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
      groups.set(key, {
        key,
        label: groupLabelForTask(task, mode, pairs, pairSkus),
        rows: [row],
        pair: mode === "article" ? taskPair(task, pairs) : null,
      });
    }
  }

  for (const group of groups.values()) {
    for (const row of group.rows) {
      row.balanceQty = Math.max(0, row.planQty - row.doneQty);
      sortPackaging(row);
    }
  }

  // Итоги группы — сумма по строкам: слитые задания уже учтены в своих строках.
  const sorted = Array.from(groups.values())
    .map((group): PlanTaskGroup => ({
      key: group.key,
      label: group.label,
      rows: group.rows,
      totalQtyPlan: sumRows(group.rows, "planQty"),
      totalQtyDone: sumRows(group.rows, "doneQty"),
      totalQtyIssued: sumRows(group.rows, "issuedQty"),
      totalQtyTransferred: sumRows(group.rows, "transferredQty"),
      // Подвес пары — один на обе позиции, поэтому группа помечается парой
      // только когда обе строки на листе действительно есть.
      pair:
        group.pair && (pairSkus.get(group.key)?.size ?? 0) > 1
          ? {
              id: group.pair.id,
              skus: Array.from(pairSkus.get(group.key) ?? []).sort(),
              quantityPerHanger: pairQuantityPerHanger(
                group.pair,
                group.rows[0] ? taskLengthMm(group.rows[0].tasks[0]) : null,
              ),
            }
          : null,
    }))
    .sort((a, b) => {
      if (b.totalQtyPlan !== a.totalQtyPlan) return b.totalQtyPlan - a.totalQtyPlan;
      return a.label.localeCompare(b.label, "ru");
    });

  // Артикул читается одним куском: группа собирается по артикулу И размеру,
  // поэтому два размера одного артикула иначе разделяли бы чужие артикулы.
  return clusterByArticle(sorted, {
    articleOf: (group) => group.rows[0]?.productSku ?? "—",
    quantityOf: (group) => group.totalQtyPlan,
  });
}
