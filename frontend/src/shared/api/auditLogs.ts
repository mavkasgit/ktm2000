import { apiClient } from "./client";

export type AuditLogEntry = {
  id: number;
  created_at: string;
  user_id: number | null;
  user_name: string | null;
  status: "success" | "error" | "info";
  title: string;
  message: string;
  section_id: number | null;
  section_name: string | null;
  section_code: string | null;
  task_ids: string | null; // Разделенные запятыми ID задач
  product_sku: string | null;
  operation_name: string | null;
  qty_text: string | null;
  comment: string | null;
  error_details: string | null;
  action?: string | null;
  entity_type?: string | null;
  entity_id?: number | null;
  changes?: Record<string, any> | null;
};

export type AuditLogsResponse = {
  items: AuditLogEntry[];
  task_statuses: Record<number, "active" | "deleted">;
  counts: Record<string, number>;
  total: number;
};

export type AuditLogCreateParams = {
  status: "success" | "error" | "info";
  title: string;
  message: string;
  section_id?: number | null;
  section_name?: string | null;
  section_code?: string | null;
  task_ids?: number[] | null;
  product_sku?: string | null;
  operation_name?: string | null;
  qty_text?: string | null;
  comment?: string | null;
  error_details?: string | null;
  action?: string | null;
  entity_type?: string | null;
  entity_id?: number | null;
  changes?: Record<string, any> | null;
};

export type GetAuditLogsParams = {
  limit?: number;
  offset?: number;
  status?: string | null;
  section_id?: number | null;
  search?: string | null;
  action?: string | null;
  entity_type?: string | null;
  sort_by?: string | null;
  sort_order?: "asc" | "desc" | null;
  date_from?: string | null;
  date_to?: string | null;
};

export async function getAuditLogs(params: GetAuditLogsParams) {
  const { data } = await apiClient.get<AuditLogsResponse>("/audit-logs", { params });
  return data;
}

export async function createAuditLog(payload: AuditLogCreateParams) {
  const { data } = await apiClient.post<AuditLogEntry>("/audit-logs", payload);
  return data;
}
