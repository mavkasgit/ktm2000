import { apiClient } from "./client";

export type ShopfloorRequestOptions = {
  singleSectionLockId?: number | null;
};

function makeRequestConfig(options?: ShopfloorRequestOptions) {
  if (!options?.singleSectionLockId) return undefined;
  return {
    headers: {
      "X-Shopfloor-Single-Section-Id": String(options.singleSectionLockId),
    },
  };
}

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

export type ReadyToTransferTask = {
  task_id: number;
  section_id: number;
  section_code: string | null;
  section_name: string | null;
  plan_position_id: number;
  route_step_id: number;
  sequence: number;
  operation_code: string | null;
  operation_name: string | null;
  product_id: number;
  product_sku: string | null;
  planned_quantity: string;
  completed_quantity: string;
  already_transferred_quantity: string;
  transferable_quantity: string;
  has_next_step: boolean;
  next_section_id: number | null;
  next_section_code: string | null;
  next_section_name: string | null;
  next_operation_name: string | null;
  next_step_sequence: number | null;
  next_step_is_final: boolean | null;
  is_final: boolean;
  completion_comment: string | null;
  dimensions: Record<string, number | string> | null;
  dimensions_label: string | null;
};

export type ReadyToTransferResponse = {
  items: ReadyToTransferTask[];
  total: number;
  limit: number;
  offset: number;
  filters: { section_id: number | null; spg_id: number | null };
};

export type ReadyToTransferListParams = {
  section_id?: number | null;
  spg_id?: number | null;
  limit?: number;
  offset?: number;
  search?: string;
  sort_by?: string;
  sort_order?: "asc" | "desc";
  product_sku?: string;
  operation_name?: string;
  next_operation_name?: string;
  next_section_name?: string;
  task_id?: number;
  plan_position_id?: number;
  transferable_qty?: string;
  /** Фильтр точного совпадения по габариту: JSON-строка (`{"length_mm":2700}`) или `null` для безразмерных. */
  dimensions?: string;
};

export type IncomingTransfer = {
  transfer_id: number;
  transfer_no: string;
  status: string;
  from_task_id: number;
  to_task_id: number;
  from_section_id: number;
  from_section_code: string;
  from_section_name: string;
  to_section_id: number;
  to_section_code: string;
  to_section_name: string;
  from_operation_name: string | null;
  to_operation_name: string | null;
  sent_quantity: string;
  accepted_quantity: string;
  rejected_quantity: string;
  remaining_quantity: string;
  comment: string | null;
  sent_at: string | null;
  created_at: string | null;
  is_post_factum: boolean;
  physical_handover_at: string | null;
  from_task_status: string;
  to_task_status: string;
  product_sku: string;
  from_line_id: number;
  from_line_sequence: number;
  plan_position_id: number;
  /** Габарит переданного (тикет #95): колонка «Размер» в UI. */
  dimensions?: Record<string, unknown> | null;
};

export type IncomingTransfersResponse = {
  section_id: number;
  incoming_transfers: IncomingTransfer[];
};

export type CreateTransferInput = {
  from_task_id: number;
  to_task_id?: number;
  quantity: number | string;
  comment?: string;
  idempotency_key?: string;
  executor_user_id?: number;
  performed_at?: string;
  accounted_at?: string;
  post_factum?: boolean;
  allow_over_plan?: boolean;
  physical_handover_at?: string;
  dimensions?: Record<string, number | string> | null;
};

export type CreateTransferResponse = {
  transfer_id: number;
  transfer_no: string;
  // Under the explicit-transfer model, transfer_send auto-accepts:
  // the response status is always "accepted" (the transfer is already
  // received on the destination by the time the API returns).
  status: string;
  to_task_id: number;
  idempotent_replay?: boolean;
};

export type FinalReleaseInput = {
  quantity: number | string;
  comment?: string;
  idempotency_key?: string;
  executor_user_id?: number;
  performed_at?: string;
  accounted_at?: string;
  // Габарит выпуска (ADR-0001): на трансформирующем финальном этапе —
  // один из выходных размеров задания; на обычном — опционален.
  dimensions?: Record<string, number | string> | null;
};

export type FinalReleaseResponse = {
  transaction_id: number;
  task_id: number;
  idempotent_replay?: boolean;
};

// ---------------------------------------------------------------------------
// API — /transfers endpoints. Under the explicit-transfer model there is
// no separate /accept step: transfer_send auto-accepts the transfer
// inline. Operators either confirm the transfer on the /transfers page
// or correct/cancel it after the fact.
// ---------------------------------------------------------------------------

export async function listReadyToTransfer(
  params: ReadyToTransferListParams = {},
  options?: ShopfloorRequestOptions,
): Promise<ReadyToTransferResponse> {
  const search = new URLSearchParams();
  if (params.section_id) search.set("section_id", String(params.section_id));
  if (params.spg_id) search.set("spg_id", String(params.spg_id));
  if (params.limit != null) search.set("limit", String(params.limit));
  if (params.offset != null) search.set("offset", String(params.offset));
  if (params.search) search.set("search", params.search);
  if (params.sort_by) search.set("sort_by", params.sort_by);
  if (params.sort_order) search.set("sort_order", params.sort_order);
  if (params.product_sku) search.set("product_sku", params.product_sku);
  if (params.operation_name) search.set("operation_name", params.operation_name);
  if (params.next_operation_name) search.set("next_operation_name", params.next_operation_name);
  if (params.next_section_name) search.set("next_section_name", params.next_section_name);
  if (params.task_id != null) search.set("task_id", String(params.task_id));
  if (params.transferable_qty) search.set("transferable_qty", params.transferable_qty);
  if (params.dimensions) search.set("dimensions", params.dimensions);
  const qs = search.toString();
  const { data } = await apiClient.get<ReadyToTransferResponse>(
    `/transfers/ready${qs ? `?${qs}` : ""}`,
    makeRequestConfig(options),
  );
  return data;
}

export async function listIncomingTransfers(
  sectionId: number,
  options?: ShopfloorRequestOptions,
): Promise<IncomingTransfersResponse> {
  const { data } = await apiClient.get<IncomingTransfersResponse>(
    `/transfers/sections/${sectionId}/incoming`,
    makeRequestConfig(options),
  );
  return data;
}

export async function createTransfer(
  payload: CreateTransferInput,
  options?: ShopfloorRequestOptions,
): Promise<CreateTransferResponse> {
  const { data } = await apiClient.post<CreateTransferResponse>(
    "/transfers",
    payload,
    makeRequestConfig(options),
  );
  return data;
}

export async function finalReleaseTask(
  taskId: number,
  payload: FinalReleaseInput,
  options?: ShopfloorRequestOptions,
): Promise<FinalReleaseResponse> {
  const { data } = await apiClient.post<FinalReleaseResponse>(
    `/shopfloor/tasks/${taskId}/final-release`,
    payload,
    makeRequestConfig(options),
  );
  return data;
}

export async function getTransferDetails(transferId: number): Promise<{
  id: number;
  transfer_no: string;
  status: string;
  from_task_id: number;
  to_task_id: number;
  sent_quantity: string;
  accepted_quantity: string | null;
  rejected_quantity: string | null;
  discrepancies: Array<{
    id: number;
    discrepancy_quantity: string;
    resolved_quantity: string;
    unresolved_quantity: string;
    status: string;
    reason: string | null;
    comment: string | null;
    links: Array<{ id: number; defect_item_id: number; defect_id: number; quantity: string }>;
  }>;
}> {
  const { data } = await apiClient.get(`/transfers/${transferId}`);
  return data;
}

export async function correctTransfer(
  transferId: number,
  payload: { quantity: number | string; comment?: string },
  options?: ShopfloorRequestOptions,
): Promise<{ transfer_id: number; status: string; quantity: string }> {
  const { data } = await apiClient.put(
    `/transfers/${transferId}`,
    payload,
    makeRequestConfig(options),
  );
  return data;
}

export async function cancelTransfer(
  transferId: number,
  comment?: string,
  options?: ShopfloorRequestOptions,
): Promise<{ transfer_id: number; status: string }> {
  const qs = comment ? `?comment=${encodeURIComponent(comment)}` : "";
  const { data } = await apiClient.post(
    `/transfers/${transferId}/cancel${qs}`,
    {},
    makeRequestConfig(options),
  );
  return data;
}

export type TransferHistoryResponse = {
  section_id: number | null;
  spg_id: number | null;
  transfers: IncomingTransfer[];
  total: number;
  limit: number;
  offset: number;
};

export type TransferHistoryListParams = {
  section_id?: number | null;
  spg_id?: number | null;
  limit?: number;
  offset?: number;
  search?: string;
  status?: string;
  sort_by?: string;
  sort_order?: "asc" | "desc";
  date_from?: string;
  date_to?: string;
  product_sku?: string;
  from_section_name?: string;
  to_section_name?: string;
};

export async function listTransferHistory(
  params: TransferHistoryListParams = {},
  options?: ShopfloorRequestOptions,
): Promise<TransferHistoryResponse> {
  const search = new URLSearchParams();
  if (params.section_id) search.set("section_id", String(params.section_id));
  if (params.spg_id) search.set("spg_id", String(params.spg_id));
  if (params.limit != null) search.set("limit", String(params.limit));
  if (params.offset != null) search.set("offset", String(params.offset));
  if (params.search) search.set("search", params.search);
  if (params.status) search.set("status", params.status);
  if (params.sort_by) search.set("sort_by", params.sort_by);
  if (params.sort_order) search.set("sort_order", params.sort_order);
  if (params.date_from) search.set("date_from", params.date_from);
  if (params.date_to) search.set("date_to", params.date_to);
  if (params.product_sku) search.set("product_sku", params.product_sku);
  if (params.from_section_name) search.set("from_section_name", params.from_section_name);
  if (params.to_section_name) search.set("to_section_name", params.to_section_name);
  const qs = search.toString();
  const { data } = await apiClient.get<TransferHistoryResponse>(
    `/transfers/history${qs ? `?${qs}` : ""}`,
    makeRequestConfig(options),
  );
  return data;
}


