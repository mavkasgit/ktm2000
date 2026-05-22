import type { ProductionPlanningRow } from "@/shared/api/productionPlans";

export const positionStatusLabels: Record<string, string> = {
  draft: "Черновик",
  invalid: "Ошибка",
  valid: "Валиден",
  approved: "Утвержден",
  released: "Запущен",
  cancelled: "Отменен",
  completed: "Завершён",
};

export const positionStatusColor: Record<string, string> = {
  draft: "bg-gray-100 text-gray-700",
  invalid: "bg-red-100 text-red-700",
  valid: "bg-green-100 text-green-700",
  approved: "bg-blue-100 text-blue-700",
  released: "bg-emerald-100 text-emerald-700",
  cancelled: "bg-red-100 text-red-700",
  completed: "bg-violet-100 text-violet-700",
};

export type ExecutionSortField = "id" | "row" | "plan" | "sku" | "name" | "qty" | "route" | "status" | "stage";

export type RouteMetaLike = Pick<
  ProductionPlanningRow,
  "route_source" | "route_origin" | "route_match_quality" | "route_assigned_at"
>;

export function formatRouteAssignedAt(value: string | null | undefined): string {
  if (!value) return "дата неизвестна";
  const dt = new Date(value);
  if (Number.isNaN(dt.getTime())) return "дата неизвестна";
  return dt.toLocaleString("ru-RU", {
    day: "2-digit",
    month: "2-digit",
    year: "numeric",
    hour: "2-digit",
    minute: "2-digit",
  });
}

export function routeMetaLabel(route: RouteMetaLike): string {
  const assignedAt = formatRouteAssignedAt(route.route_assigned_at);
  if (route.route_origin === "manual_confirmed" || route.route_source === "manual") {
    return `вручную • ${assignedAt}`;
  }
  if (route.route_origin === "auto" || route.route_source === "auto") {
    const quality = route.route_match_quality === "exact" ? "полное" : "скорректирован";
    return `автомаппинг (${quality}) • ${assignedAt}`;
  }
  if (route.route_origin === "legacy" || route.route_source === "legacy") {
    return "legacy • дата неизвестна";
  }
  if (route.route_source === "missing") {
    return "не найден";
  }
  return "—";
}

export function fmtQty(value: number): string {
  if (Number.isInteger(value)) {
    return String(value);
  }
  return value.toFixed(3).replace(/\.?0+$/, "");
}

export function planPreviewUrl(planId: number): string {
  return `/plans/${planId}/preview`;
}

export function getLaunchBlockReason(row: ProductionPlanningRow): string | null {
  if (row.is_completed) return "Уже завершено";
  if (row.has_tasks || row.is_released) return "Уже запущено";
  if (row.position_status !== "approved") return `Статус "${positionStatusLabels[row.position_status] || row.position_status}"`;
  if (!row.route_id) return row.route_error || "Нет маршрута";
  return null;
}

export function getCancelBlockReason(row: ProductionPlanningRow): string | null {
  if (!["approved", "released"].includes(row.position_status)) {
    return `Статус "${positionStatusLabels[row.position_status] || row.position_status}"`;
  }
  return null;
}

export function getRestoreBlockReason(row: ProductionPlanningRow): string | null {
  if (row.position_status !== "cancelled") {
    return `Статус "${positionStatusLabels[row.position_status] || row.position_status}"`;
  }
  return null;
}

export function getSoftDeleteBlockReason(row: ProductionPlanningRow): string | null {
  if (row.position_status !== "cancelled") {
    return `Статус "${positionStatusLabels[row.position_status] || row.position_status}"`;
  }
  return null;
}

export function getManualPassBlockReason(row: ProductionPlanningRow): string | null {
  if (!row.route_id) return "Нет маршрута";
  if (!["approved", "released"].includes(row.position_status)) {
    return `Статус "${positionStatusLabels[row.position_status] || row.position_status}"`;
  }
  if (row.is_completed) return "Уже завершено";
  return null;
}

/**
 * Map a column filter field to its string value for a given row.
 */
export function getCellValue(row: ProductionPlanningRow, field: ExecutionSortField): string {
  switch (field) {
    case "id":
      return String(row.plan_position_id);
    case "row":
      return String(row.source_row_number ?? "");
    case "plan":
      return `${row.production_plan_id}`;
    case "sku":
      return row.source_sku;
    case "name":
      return row.source_name || "";
    case "qty":
      return fmtQty(row.quantity);
    case "route":
      return row.route_name || "Не назначен";
    case "status":
      return row.is_completed ? "completed" : row.position_status;
    case "stage":
      return row.current_stage_section_name || "—";
    default:
      return "";
  }
}
