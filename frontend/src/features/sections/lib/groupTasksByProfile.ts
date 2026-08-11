/**
 * lib/groupTasksByProfile.ts
 * ==========================
 * Логика группировки задач по профилю.
 *
 * АРХИТЕКТУРНОЕ РЕШЕНИЕ — группировка на фронтенде, не в SQL:
 *   - Профиль можно менять без запроса к серверу (мгновенно)
 *   - Один и тот же ответ API используется при любом профиле
 */

import type { SectionBoardTask, TaskGroup } from "@/shared/api/shopfloor";
import type { GroupingProfile } from "./groupingProfiles";
import { colorNameLabels, operationCodeLabels } from "@/shared/lib/generated-labels";
import { formatDimensionsLabel } from "@/shared/api/stock";

// ---------------------------------------------------------------------------
// Размер как принудительный критерий
// ---------------------------------------------------------------------------

/** Маркер «без размеров» в ключе группы — отдельная строка, не смешивается
 *  с размерными строками того же артикула (ADR-0001, CONTEXT). */
const NO_DIMENSIONS_KEY = "__no_dimensions__";

/**
 * Размер задания для группировки (принудительный критерий).
 *
 * У резки (трансформирующий этап, ADR-0002) размер — вход
 * (`input_dimensions`); у остальных этапов — габарит задания (`dimensions`).
 * Пары (`source_sku` с `+`) несут в этих полях уже разрешённый размер
 * пересечения компонентов (бэкенд отдаёт его в `dimensions`/`input_dimensions`).
 */
export function taskGroupingDimensions(
  task: SectionBoardTask,
): Record<string, unknown> | null {
  if (task.transforms_dimensions) return task.input_dimensions ?? null;
  return task.dimensions ?? null;
}

/** Канонический строковый ключ размера для ключа группы. */
function dimensionsKey(dims: Record<string, unknown> | null): string {
  if (!dims) return NO_DIMENSIONS_KEY;
  const keys = Object.keys(dims).sort();
  if (keys.length === 0) return NO_DIMENSIONS_KEY;
  return keys.map((k) => `${k}=${String(dims[k])}`).join("|");
}

/** Канонический ключ размера задачи (для reuse в bulk-панели и т.п.). */
export function taskGroupingDimensionsKey(task: SectionBoardTask): string {
  return dimensionsKey(taskGroupingDimensions(task));
}

/** Числовой размер задачи (`length_mm`) для сортировки; безразмерные — -Infinity. */
export function taskSizeMm(task: SectionBoardTask): number {
  const dims = taskGroupingDimensions(task);
  const mm = dims?.length_mm;
  return typeof mm === "number" && Number.isFinite(mm) ? mm : -Infinity;
}


// ---------------------------------------------------------------------------
// Построение ключа группы
// ---------------------------------------------------------------------------

function buildGroupKey(
  task: SectionBoardTask,
  profile: GroupingProfile,
): string {
  // Check if there are any production operations BEFORE the current stage.
  // Empty route_history means this is the first production section.
  const hasHistoryBefore = (task.route_history ?? []).length > 0;

  // Принудительная часть ключа: «артикул + размер» (не отключается профилем).
  const parts: string[] = [
    task.product_sku,
    dimensionsKey(taskGroupingDimensions(task)),
  ];

  for (const criterion of profile.criteria) {
    if (criterion === "productSku") continue; // артикул уже в принудительной части
    switch (criterion) {
      case "routeStepId":
        parts.push(String(task.route_step_id));
        break;

      case "operationCode":
        // For routeHistory profile: skip operationCode if there's no history before current stage.
        // On the first stage, all tasks should group by productSku only (before = no current section op).
        // For routeHistoryAfter profile: always include operationCode to split by current section's operation.
        if (profile.criteria.includes("routeHistory") && !hasHistoryBefore) {
          parts.push("__no_history__");
        } else {
          parts.push(task.operation_code ?? "—");
        }
        break;

      case "outputKind":
        parts.push(task.output_kind ?? "—");
        break;

      case "sourceRef":
        parts.push(task.source_ref ?? "—");
        break;

      case "fingerprint":
        parts.push(task.source_fingerprint ?? "—");
        break;

      case "routeHistory":
        parts.push((task.route_history_full ?? [])
          .map((op: any) => typeof op === "string" ? op : (op.operation_code || op.operation_name || ""))
          .join("→"));
        break;

      case "routeHistoryAfter":
        parts.push((task.route_history_after_full ?? [])
          .map((op: any) => typeof op === "string" ? op : (op.operation_code || op.operation_name || ""))
          .join("→"));
        break;

      case "customField": {
        const fields = profile.customFields ?? [];
        if (fields.length === 0) {
          parts.push("__all__");
        } else {
          parts.push(fields
            .map((field) => String(task.source_payload[field] ?? "—"))
            .join("|"));
        }
        break;
      }
    }
  }

  return parts.join("__");
}


// ---------------------------------------------------------------------------
// Построение читаемого заголовка группы
// ---------------------------------------------------------------------------

function buildGroupLabel(
  task: SectionBoardTask,
  profile: GroupingProfile,
): string {
  const parts: string[] = [];

  // Принудительная часть подписи: «артикул · размер» (размер из входа резки
  // или габарита задания; безразмерные — «—»).
  parts.push(task.product_sku);
  parts.push(formatDimensionsLabel(taskGroupingDimensions(task)));

  for (const criterion of profile.criteria) {
    if (criterion === "productSku") continue;
    switch (criterion) {
      case "routeStepId":
        parts.push(`этап ${task.sequence}`);
        break;

      case "operationCode":
        if (task.operation_code) {
          parts.push(operationCodeLabels[task.operation_code] ?? task.operation_code);
        }
        break;

      case "outputKind":
        if (task.output_kind) {
          parts.push(colorNameLabels[task.output_kind] ?? task.output_kind);
        }
        break;

      case "sourceRef":
        if (task.source_ref) {
          parts.push(task.source_ref);
        }
        break;

      case "fingerprint":
        if (task.operation_code) parts.push(task.operation_code);
        if (task.output_kind) parts.push(task.output_kind);
        break;

      case "routeHistory":
        if (task.route_history_full && task.route_history_full.length > 0) {
          parts.push(task.route_history_full
            .map((op: any) => typeof op === "string" ? op : op.operation_name)
            .join(" → "));
        }
        break;

      case "routeHistoryAfter":
        if (task.route_history_after_full && task.route_history_after_full.length > 0) {
          parts.push(task.route_history_after_full
            .map((op: any) => typeof op === "string" ? op : op.operation_name)
            .join(" → "));
        }
        break;

      case "customField":
        for (const field of profile.customFields ?? []) {
          const val = task.source_payload[field];
          if (val !== null && val !== undefined) {
            parts.push(`${field}: ${val}`);
          }
        }
        break;
    }
  }

  return parts.join(" · ");
}


// ---------------------------------------------------------------------------
// Главная функция группировки
// ---------------------------------------------------------------------------

export function groupTasksByProfile(
  tasks: SectionBoardTask[],
  profile: GroupingProfile,
): TaskGroup[] {
  const map = new Map<string, TaskGroup>();

  for (const task of tasks) {
    const key = buildGroupKey(task, profile);

    if (!map.has(key)) {
      map.set(key, {
        key,
        label: buildGroupLabel(task, profile),
        tasks: [],
        totalQtyPlan: 0,
        totalQtyDone: 0,
      });
    }

    const group = map.get(key)!;
    group.tasks.push(task);

    const completedQty = parseFloat(task.cache.completed_quantity);
    const plannedQty = parseFloat(task.planned_quantity);
    group.totalQtyPlan += plannedQty;
    group.totalQtyDone += completedQty;
  }

  return sortGroupsByQuantityAndSize(Array.from(map.values()));
}


// ---------------------------------------------------------------------------
// Утилиты для работы с группами
// ---------------------------------------------------------------------------

/** Числовой размер группы (`length_mm`) для сортировки; безразмерные — -Infinity. */
function groupSizeMm(group: TaskGroup): number {
  return taskSizeMm(group.tasks[0]);
}

/**
 * Сортировка групп/строк по количеству убыв.; при равных — размер убыв.
 * (3 м → 1 м), где размер — `length_mm` габарита (для пар и 2D-габаритов
 * без `length_mm` — безразмерные, в конец).
 */
export function sortGroupsByQuantityAndSize(groups: TaskGroup[]): TaskGroup[] {
  return [...groups].sort((a, b) => {
    const qtyDiff = b.totalQtyPlan - a.totalQtyPlan;
    if (qtyDiff !== 0) return qtyDiff;
    return groupSizeMm(b) - groupSizeMm(a);
  });
}

export function groupStatus(
  group: TaskGroup,
): "done" | "blocked" | "in_work" | "partially" | "pending" {
  const statuses = new Set(group.tasks.map((t) => t.status));

  if (statuses.has("blocked")) return "blocked";

  const allDone = group.tasks.every((t) => t.status === "done");
  if (allDone) return "done";

  if (statuses.has("in_work")) return "in_work";

  const hasProgress =
    statuses.has("done") || statuses.has("partially");
  if (hasProgress) return "partially";

  return "pending";
}


export function sortGroupsByPriority(groups: TaskGroup[]): TaskGroup[] {
  const ORDER = { in_work: 0, partially: 1, pending: 2, done: 3, blocked: 4 };
  return [...groups].sort((a, b) => {
    const sa = groupStatus(a);
    const sb = groupStatus(b);
    return (ORDER[sa] ?? 9) - (ORDER[sb] ?? 9);
  });
}
