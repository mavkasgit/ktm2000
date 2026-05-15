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

export type SectionBoardTask = {
  id: number;
  product_id: number;
  section_plan_line_id: number;
  plan_position_id: number;
  route_step_id: number;
  sequence: number;
  operation_code: string | null;
  operation_name: string | null;
  planned_quantity: string;
  status: string;
  cache: {
    available_quantity: string;
    issued_quantity: string;
    in_work_quantity: string;
    completed_quantity: string;
    transferred_quantity: string;
    received_quantity: string;
    rejected_quantity: string;
    remaining_quantity: string;
  };
  previous_stage: {
    section_plan_line_id: number;
    completed_quantity: string;
    transferred_quantity: string;
    received_quantity: string;
  } | null;
  next_task_id: number | null;
  next_task_status: string | null;
  next_operation_name: string | null;
};

export type SectionBoardResponse = {
  section_id: number;
  tasks: SectionBoardTask[];
};

export type DailyStatsRow = {
  date: string;
  good_quantity: string;
  rejected_quantity: string;
  op_count: number;
  avg_accounting_delay_seconds: string;
};

export type DailyStatsResponse = {
  section_id: number;
  daily_stats: DailyStatsRow[];
};

export type SectionSummary = {
  section_id: number;
  section_code: string;
  section_name: string;
  kind: string;
  sort_order: number;
  icon: string | null;
  icon_color: string | null;
  total_tasks: number;
  ready_count: number;
  in_progress_count: number;
  waiting_count: number;
  incoming_transfers_count: number;
};

export type SectionsSummaryResponse = {
  sections: SectionSummary[];
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
  from_task_status: string;
  to_task_status: string;
};

export type IncomingTransfersResponse = {
  section_id: number;
  incoming_transfers: IncomingTransfer[];
};

export type PrepareTaskInput = {
  plan_position_id: number;
  section_id: number;
  quantity: number | string;
  idempotency_key?: string;
};

export type PrepareTaskResponse = {
  task_id: number;
  status: string;
  idempotent_replay?: boolean;
};

export type CompleteTaskInput = {
  good_quantity: number | string;
  defect_quantity: number | string;
  defect_reason?: string;
  comment?: string;
  idempotency_key?: string;
  executor_user_id?: number;
  performed_at?: string;
  accounted_at?: string;
};

export type IssueTaskInput = {
  quantity: number | string;
  comment?: string;
  idempotency_key?: string;
  executor_user_id?: number;
  performed_at?: string;
  accounted_at?: string;
};

export type TransferSendInput = {
  from_task_id: number;
  to_task_id?: number;
  quantity: number | string;
  comment?: string;
  idempotency_key?: string;
  executor_user_id?: number;
  performed_at?: string;
  accounted_at?: string;
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

export async function getSectionBoard(
  sectionId: number,
  params?: { date_from?: string; date_to?: string; status?: string },
  options?: ShopfloorRequestOptions
): Promise<SectionBoardResponse> {
  const search = new URLSearchParams();
  if (params?.date_from) search.set("date_from", params.date_from);
  if (params?.date_to) search.set("date_to", params.date_to);
  if (params?.status) search.set("status", params.status);
  const qs = search.toString();
  const { data } = await apiClient.get<SectionBoardResponse>(
    `/shopfloor/sections/${sectionId}/board${qs ? `?${qs}` : ""}`,
    makeRequestConfig(options)
  );
  return data;
}

export async function getSectionDailyStats(
  sectionId: number,
  params: { date_from: string; date_to: string },
  options?: ShopfloorRequestOptions
): Promise<DailyStatsResponse> {
  const search = new URLSearchParams({
    date_from: params.date_from,
    date_to: params.date_to,
  });
  const { data } = await apiClient.get<DailyStatsResponse>(
    `/shopfloor/sections/${sectionId}/daily-stats?${search.toString()}`,
    makeRequestConfig(options)
  );
  return data;
}

export async function getSectionsSummary(): Promise<SectionsSummaryResponse> {
  const { data } = await apiClient.get<SectionsSummaryResponse>("/shopfloor/sections/summary");
  return data;
}

export async function getIncomingTransfers(
  sectionId: number,
  options?: ShopfloorRequestOptions
): Promise<IncomingTransfersResponse> {
  const { data } = await apiClient.get<IncomingTransfersResponse>(
    `/shopfloor/sections/${sectionId}/incoming-transfers`,
    makeRequestConfig(options)
  );
  return data;
}

export async function prepareSectionTask(
  payload: PrepareTaskInput
): Promise<PrepareTaskResponse> {
  const { data } = await apiClient.post<PrepareTaskResponse>(
    "/shopfloor/section-tasks/prepare",
    payload
  );
  return data;
}

export async function completeTask(
  taskId: number,
  payload: CompleteTaskInput,
  options?: ShopfloorRequestOptions
): Promise<{ task_id: number; movement_ids: number[]; defect_id: number | null; status: string; idempotent_replay?: boolean }> {
  const { data } = await apiClient.post(
    `/shopfloor/tasks/${taskId}/complete`,
    payload,
    makeRequestConfig(options)
  );
  return data;
}

export async function issueTask(
  taskId: number,
  payload: IssueTaskInput,
  options?: ShopfloorRequestOptions
): Promise<{ movement_id: number; task_id: number; status: string; idempotent_replay?: boolean }> {
  const { data } = await apiClient.post(
    `/shopfloor/tasks/${taskId}/issue`,
    payload,
    makeRequestConfig(options)
  );
  return data;
}

export async function createTransfer(
  payload: TransferSendInput,
  options?: ShopfloorRequestOptions
): Promise<{ transfer_id: number; transfer_no: string; status: string; idempotent_replay?: boolean }> {
  const { data } = await apiClient.post(
    "/shopfloor/transfers",
    payload,
    makeRequestConfig(options)
  );
  return data;
}

export async function acceptTransfer(
  transferId: number,
  payload: AcceptTransferInput,
  options?: ShopfloorRequestOptions
): Promise<{ transfer_id: number; status: string; discrepancy_id: number | null }> {
  const { data } = await apiClient.post(
    `/shopfloor/transfers/${transferId}/accept`,
    payload,
    makeRequestConfig(options)
  );
  return data;
}
