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
};

export type ReadyToTransferResponse = {
  items: ReadyToTransferTask[];
  filters: { section_id: number | null; spg_id: number | null };
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
  physical_handover_at?: string;
};

export type AcceptTransferInput = {
  accepted_quantity: number | string;
  rejected_quantity: number | string;
  reason?: string;
  comment?: string;
  idempotency_key?: string;
  executor_user_id?: number;
  performed_at?: string;
  accounted_at?: string;
};

export type CreateTransferResponse = {
  transfer_id: number;
  transfer_no: string;
  status: string;
  to_task_id: number;
  idempotent_replay?: boolean;
};

export type AcceptTransferResponse = {
  transfer_id: number;
  status: string;
  discrepancy_id: number | null;
};

// ---------------------------------------------------------------------------
// API — new /transfers endpoints. Old /shopfloor/transfers endpoints still
// work but are deprecated for new code.
// ---------------------------------------------------------------------------

export async function listReadyToTransfer(
  params: { section_id?: number | null; spg_id?: number | null } = {},
  options?: ShopfloorRequestOptions,
): Promise<ReadyToTransferResponse> {
  const search = new URLSearchParams();
  if (params.section_id) search.set("section_id", String(params.section_id));
  if (params.spg_id) search.set("spg_id", String(params.spg_id));
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

export async function acceptTransfer(
  transferId: number,
  payload: AcceptTransferInput,
  options?: ShopfloorRequestOptions,
): Promise<AcceptTransferResponse> {
  const { data } = await apiClient.post<AcceptTransferResponse>(
    `/transfers/${transferId}/accept`,
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

export async function listTransferHistory(
  params: { section_id?: number | null; spg_id?: number | null; limit?: number } = {},
  options?: ShopfloorRequestOptions,
): Promise<{ section_id: number | null; spg_id: number | null; transfers: IncomingTransfer[] }> {
  const search = new URLSearchParams();
  if (params.section_id) search.set("section_id", String(params.section_id));
  if (params.spg_id) search.set("spg_id", String(params.spg_id));
  if (params.limit) search.set("limit", String(params.limit));
  const qs = search.toString();
  const { data } = await apiClient.get<{ section_id: number | null; spg_id: number | null; transfers: IncomingTransfer[] }>(
    `/transfers/history${qs ? `?${qs}` : ""}`,
    makeRequestConfig(options),
  );
  return data;
}


