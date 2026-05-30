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
import type { GroupingCriterion, GroupingProfile } from "./groupingProfiles";


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

  const parts = profile.criteria.map((criterion: GroupingCriterion) => {
    switch (criterion) {
      case "productSku":
        return task.product_sku;

      case "routeStepId":
        return String(task.route_step_id);

      case "operationCode":
        // For routeHistory profile: skip operationCode if there's no history before current stage.
        // On the first stage, all tasks should group by productSku only (before = no current section op).
        // For routeHistoryAfter profile: always include operationCode to split by current section's operation.
        if (profile.criteria.includes("routeHistory") && !hasHistoryBefore) {
          return "__no_history__";
        }
        return task.operation_code ?? "—";

      case "outputKind":
        return task.output_kind ?? "—";

      case "sourceRef":
        return task.source_ref ?? "—";

      case "fingerprint":
        return task.source_fingerprint ?? "—";

      case "routeHistory":
        return (task.route_history_full ?? [])
          .map((op: any) => typeof op === "string" ? op : (op.operation_code || op.operation_name || ""))
          .join("→");

      case "routeHistoryAfter":
        return (task.route_history_after_full ?? [])
          .map((op: any) => typeof op === "string" ? op : (op.operation_code || op.operation_name || ""))
          .join("→");

      case "customField": {
        const fields = profile.customFields ?? [];
        if (fields.length === 0) {
          return "__all__";
        }
        return fields
          .map((field) => String(task.source_payload[field] ?? "—"))
          .join("|");
      }
    }
  });

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

  parts.push(task.product_sku);

  for (const criterion of profile.criteria) {
    switch (criterion) {
      case "productSku":
        break;

      case "routeStepId":
        parts.push(`этап ${task.sequence}`);
        break;

      case "operationCode":
        if (task.operation_code) {
          const opLabels: Record<string, string> = {
            press_window: "окно",
            press_comb:   "гребенка",
            anodize:      "анодирование",
            cut:          "порезка",
          };
          parts.push(opLabels[task.operation_code] ?? task.operation_code);
        }
        break;

      case "outputKind":
        if (task.output_kind) {
          const kindLabels: Record<string, string> = {
            silver:    "серебро",
            black:     "чёрный",
            bronze:    "бронза",
            champagne: "шампань",
            natural:   "натуральный",
          };
          parts.push(kindLabels[task.output_kind] ?? task.output_kind);
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

  return Array.from(map.values());
}


// ---------------------------------------------------------------------------
// Утилиты для работы с группами
// ---------------------------------------------------------------------------

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
