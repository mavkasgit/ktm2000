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
  const s = task.signature;

  const parts = profile.criteria.map((criterion: GroupingCriterion) => {
    switch (criterion) {
      case "productSku":
        return task.product_sku;

      case "routeStepId":
        return String(task.route_step_id);

      case "operationCode":
        return s.operation_code ?? "—";

      case "outputKind":
        return s.output_kind ?? "—";

      case "sourceRef":
        return s.source_ref ?? "—";

      case "fingerprint":
        return s.source_fingerprint;

      case "routeHistory":
        return (s.route_history ?? [])
          .map((op: any) => typeof op === "string" ? op : (op.operation_code || op.operation_name || ""))
          .join("→");

      case "routeHistoryAfter":
        return (s.route_history_after ?? [])
          .map((op: any) => typeof op === "string" ? op : (op.operation_code || op.operation_name || ""))
          .join("→");

      case "customField": {
        const fields = profile.customFields ?? [];
        if (fields.length === 0) {
          return "__all__";
        }
        return fields
          .map((field) => String(s.source_payload[field] ?? "—"))
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
  const s = task.signature;
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
        if (s.operation_code) {
          const opLabels: Record<string, string> = {
            press_window: "окно",
            press_comb:   "гребенка",
            anodize:      "анодирование",
            cut:          "порезка",
          };
          parts.push(opLabels[s.operation_code] ?? s.operation_code);
        }
        break;

      case "outputKind":
        if (s.output_kind) {
          const kindLabels: Record<string, string> = {
            silver:    "серебро",
            black:     "чёрный",
            bronze:    "бронза",
            champagne: "шампань",
            natural:   "натуральный",
          };
          parts.push(kindLabels[s.output_kind] ?? s.output_kind);
        }
        break;

      case "sourceRef":
        if (s.source_ref) {
          parts.push(s.source_ref);
        }
        break;

      case "fingerprint":
        if (s.operation_code) parts.push(s.operation_code);
        if (s.output_kind) parts.push(s.output_kind);
        break;

      case "routeHistory":
        if (s.route_history && s.route_history.length > 0) {
          parts.push(s.route_history
            .map((op: any) => typeof op === "string" ? op : op.operation_name)
            .join(" → "));
        }
        break;

      case "routeHistoryAfter":
        if (s.route_history_after && s.route_history_after.length > 0) {
          parts.push(s.route_history_after
            .map((op: any) => typeof op === "string" ? op : op.operation_name)
            .join(" → "));
        }
        break;

      case "customField":
        for (const field of profile.customFields ?? []) {
          const val = s.source_payload[field];
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
