import type { ProductionPlanningRow } from "@/shared/api/productionPlans";
import { formatDimensionsLabel } from "@/shared/api/stock";
import { fmtQty } from "@/shared/utils/fmtQty";
import { statusLabels } from "@/shared/lib/generated-labels";

export { statusLabels as positionStatusLabels };

export const positionStatusColor: Record<string, string> = {
  draft: "bg-gray-100 text-gray-700",
  invalid: "bg-red-100 text-red-700",
  valid: "bg-green-100 text-green-700",
  approved: "bg-blue-100 text-blue-700",
  released: "bg-emerald-100 text-emerald-700",
  cancelled: "bg-red-100 text-red-700",
  completed: "bg-violet-100 text-violet-700",
};

export type ExecutionSortField = "id" | "row" | "plan" | "sku" | "name" | "qty" | "route" | "status" | "stage" | "dimensions";

export function planPreviewUrl(planId: number): string {
  return `/plans/${planId}/preview`;
}

export function getLaunchBlockReason(row: ProductionPlanningRow): string | null {
  if (row.is_completed) return "Уже завершено";
  if (row.has_tasks || row.is_released) return "Уже запущено";
  if (row.position_status !== "approved") return `Статус "${statusLabels[row.position_status] || row.position_status}"`;
  if (!row.route_id) return row.route_error || "Нет маршрута";
  return null;
}

export function getCancelBlockReason(row: ProductionPlanningRow): string | null {
  if (!["approved", "released"].includes(row.position_status)) {
    return `Статус "${statusLabels[row.position_status] || row.position_status}"`;
  }
  return null;
}

export function getRestoreBlockReason(row: ProductionPlanningRow): string | null {
  if (row.position_status !== "cancelled") {
    return `Статус "${statusLabels[row.position_status] || row.position_status}"`;
  }
  return null;
}

export function getSoftDeleteBlockReason(row: ProductionPlanningRow): string | null {
  if (row.position_status !== "cancelled") {
    return `Статус "${statusLabels[row.position_status] || row.position_status}"`;
  }
  return null;
}

export function getManualPassBlockReason(row: ProductionPlanningRow): string | null {
  if (!row.route_id) return "Нет маршрута";
  if (!["approved", "released"].includes(row.position_status)) {
    return `Статус "${statusLabels[row.position_status] || row.position_status}"`;
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
    case "dimensions":
      return row.dimensions_label ?? formatDimensionsLabel(row.dimensions);
    default:
      return "";
  }
}
