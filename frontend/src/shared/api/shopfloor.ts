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

export interface RouteHistoryOp {
  operation_code: string;
  operation_name: string;
  is_significant: boolean;
  icon?: string | null;
  icon_color?: string | null;
}

export type TaskStatus = "pending" | "in_work" | "done" | "partially" | "blocked";

export type TaskGroup = {
  key: string;
  label: string;
  tasks: SectionBoardTask[];
  totalQtyPlan: number;
  totalQtyDone: number;
};

export type SectionBoardTask = {
  id: number;
  product_id: number;
  product_sku: string;
  section_plan_line_id: number;
  plan_position_id: number;
  route_step_id: number;
  sequence: number;
  operation_code: string | null;
  operation_name: string | null;
  is_significant: boolean;
  icon?: string | null;
  icon_color?: string | null;
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
  source_ref: string | null;
  source_payload: Record<string, unknown>;
  source_fingerprint: string | null;
  // --- новые поля: трансформация артикула ---
  input_sku: string;
  output_sku: string;
  display_sku: string;
  route_history: RouteHistoryOp[];
  route_history_after: RouteHistoryOp[];
  route_history_full: RouteHistoryOp[];
  route_history_after_full: RouteHistoryOp[];
  // --- combined operations ---
  is_combined_primary: boolean;
  combined_task_ids: number[];
  combined_operation_names: string[];
  combined_operation_codes: (string | null)[];
};

export type SectionBoardResponse = {
  section_id: number;
  tasks: SectionBoardTask[];
  available_operations: SectionOperation[];
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
  product_sku: string;
  from_line_id: number;
  from_line_sequence: number;
  plan_position_id: number;
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

// ---------------------------------------------------------------------------
// Утилиты для работы с задачами
// ---------------------------------------------------------------------------

/**
 * Проверяет, является ли операция трансформирующей (меняет артикул).
 */
export function isTransformingTask(task: SectionBoardTask): boolean {
  return task.input_sku !== task.output_sku;
}

/**
 * Процент выполнения задачи (0–100).
 */
export function taskProgress(task: SectionBoardTask): number {
  const plan = parseFloat(task.planned_quantity);
  if (plan === 0) return 0;
  return Math.min(100, Math.round((parseFloat(task.cache.completed_quantity) / plan) * 100));
}

/**
 * Процент выполнения группы.
 */
export function groupProgress(group: TaskGroup): number {
  if (group.totalQtyPlan === 0) return 0;
  return Math.min(
    100,
    Math.round((group.totalQtyDone / group.totalQtyPlan) * 100),
  );
}

// ---------------------------------------------------------------------------
// Payload-keys API — для кастомных полей группировки
// ---------------------------------------------------------------------------

/**
 * Загружает уникальные ключи source_payload для участка.
 * Используется в GroupingSettingsModal для чекбоксов кастомных полей.
 */
export async function getSectionPayloadKeys(
  sectionId: number,
  options?: ShopfloorRequestOptions,
): Promise<string[]> {
  const { data } = await apiClient.get<{ keys: string[] }>(
    `/shopfloor/sections/${sectionId}/payload-keys`,
    makeRequestConfig(options),
  );
  return data.keys;
}

export interface SectionOperation {
  id: number;
  operation_code: string;
  operation_name: string;
  is_significant: boolean;
  icon?: string | null;
  icon_color?: string | null;
  group_code?: string | null;
}

export async function getSectionOperations(
  sectionId: number,
): Promise<SectionOperation[]> {
  const { data } = await apiClient.get<SectionOperation[]>(
    `/shopfloor/sections/${sectionId}/operations`,
  );
  return data;
}

export async function updateSectionOperation(
  sectionId: number,
  opId: number,
  payload: { is_significant?: boolean; icon?: string | null; icon_color?: string | null },
): Promise<SectionOperation> {
  const { data } = await apiClient.patch<SectionOperation>(
    `/shopfloor/sections/${sectionId}/operations/${opId}`,
    payload,
  );
  return data;
}

export async function createSectionOperation(
  sectionId: number,
  payload: { operation_code: string; operation_name: string; is_significant?: boolean; icon?: string | null; icon_color?: string | null },
): Promise<SectionOperation> {
  const { data } = await apiClient.post<SectionOperation>(
    `/shopfloor/sections/${sectionId}/operations`,
    payload,
  );
  return data;
}

export async function deleteSectionOperation(
  sectionId: number,
  opId: number,
): Promise<{ status: string }> {
  const { data } = await apiClient.delete<{ status: string }>(
    `/shopfloor/sections/${sectionId}/operations/${opId}`,
  );
  return data;
}

export async function setTaskOperation(
  taskId: number,
  operationCode: string,
): Promise<{ task_id: number; operation_code: string; operation_name: string }> {
  const { data } = await apiClient.patch<{ task_id: number; operation_code: string; operation_name: string }>(
    `/shopfloor/tasks/${taskId}/operation`,
    { operation_code: operationCode },
  );
  return data;
}

// ---------------------------------------------------------------------------
// Warehouse Remainders API
// ---------------------------------------------------------------------------

export type CompletedStage = {
  section_id: number;
  operation_code: string;
  operation_name: string;
  sequence: number;
};

export type WarehouseRemainder = {
  id: number;
  product_id: number;
  product_sku: string;
  product_name: string;
  section_id: number;
  section_code: string;
  section_name: string;
  route_step_id: number;
  route_step_sequence: number;
  operation_code: string | null;
  operation_name: string | null;
  section_plan_line_id: number;
  origin_task_id: number;
  remainder_quantity: string;
  original_issued: string;
  completed_stages: CompletedStage[];
  created_at: string | null;
};

export type WarehouseRemaindersResponse = {
  remainders: WarehouseRemainder[];
};

export async function getWarehouseRemainders(
  sectionId?: number,
): Promise<WarehouseRemaindersResponse> {
  const params = new URLSearchParams();
  if (sectionId) params.set("section_id", String(sectionId));
  const qs = params.toString();
  const { data } = await apiClient.get<WarehouseRemaindersResponse>(
    `/shopfloor/remainders${qs ? `?${qs}` : ""}`,
  );
  return data;
}

export type ReturnRemainderInput = {
  task_id: number;
  quantity: number | string;
  comment?: string;
  idempotency_key?: string;
  executor_user_id?: number;
  performed_at?: string;
  accounted_at?: string;
};

export type ConsumeRemainderInput = {
  remainder_id: number;
  task_id: number;
  quantity: number | string;
  comment?: string;
  idempotency_key?: string;
  executor_user_id?: number;
  performed_at?: string;
  accounted_at?: string;
};

export async function returnRemainder(
  payload: ReturnRemainderInput,
  options?: ShopfloorRequestOptions,
): Promise<{ movement_id: number; remainder_id: number; task_id: number; idempotent_replay?: boolean }> {
  const { data } = await apiClient.post(
    "/shopfloor/remainders/return",
    payload,
    makeRequestConfig(options),
  );
  return data;
}

export async function consumeRemainder(
  payload: ConsumeRemainderInput,
  options?: ShopfloorRequestOptions,
): Promise<{ movement_id: number; remainder_id: number; task_id: number; idempotent_replay?: boolean }> {
  const { data } = await apiClient.post(
    "/shopfloor/remainders/consume",
    payload,
    makeRequestConfig(options),
  );
  return data;
}
