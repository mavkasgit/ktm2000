import { apiClient } from "./client";

export type PlanStatus = "draft" | "validated" | "approved" | "partially_released" | "released" | "cancelled";
export type PlanPositionStatus = "draft" | "invalid" | "valid" | "approved" | "released" | "cancelled";
export type ReleaseBatchType = "near_term" | "weekly" | "future_preparation" | "manual";

export type ProductionPlanPreview = Record<string, unknown> & {
  id?: number;
  status?: PlanStatus;
  positions?: Record<string, unknown>[];
};

export type ApprovePositionResponse = {
  id: number;
  production_plan_id: number;
  status: PlanPositionStatus;
  validation_status: string;
  validation_errors: Record<string, unknown> | null;
};

export type CreateReleaseBatchPositionInput = {
  plan_position_id: number;
  release_quantity?: string | number;
};

export type CreatePlanReleaseBatchInput = {
  name?: string;
  batch_type?: ReleaseBatchType;
  positions?: CreateReleaseBatchPositionInput[];
};

export type ReleaseBatchSummary = Record<string, unknown>;

export type PlanSummary = {
  id: number;
  plan_no: string;
  name: string;
  status: PlanStatus;
  period_start: string | null;
  period_end: string | null;
  total_positions: number;
  draft_positions: number;
  approved_positions: number;
  released_positions: number;
  created_at: string;
};

export async function listPlans() {
  const { data } = await apiClient.get<PlanSummary[]>("/production-plans");
  return data;
}

export async function previewProductionPlan(productionPlanId: number) {
  const { data } = await apiClient.get<ProductionPlanPreview>(`/production-plans/${productionPlanId}/preview`);
  return data;
}

export async function applyProductionPlanChangeSet(
  productionPlanId: number,
  changeSetId: number,
  options?: { skipInvalid?: boolean },
) {
  const { data } = await apiClient.post<ProductionPlanPreview>(
    `/production-plans/${productionPlanId}/change-sets/${changeSetId}/apply`,
    undefined,
    {
      params: {
        skip_invalid: options?.skipInvalid || undefined,
      },
    },
  );
  return data;
}

export async function rollbackProductionPlanChangeSet(productionPlanId: number, changeSetId: number) {
  const { data } = await apiClient.post<ProductionPlanPreview>(
    `/production-plans/${productionPlanId}/change-sets/${changeSetId}/rollback`,
  );
  return data;
}

export async function discardProductionPlanChangeSet(productionPlanId: number, changeSetId: number) {
  const { data } = await apiClient.delete<{ deleted: boolean; change_set_id: number }>(
    `/production-plans/${productionPlanId}/change-sets/${changeSetId}`,
  );
  return data;
}

export async function approveProductionPlanPosition(
  productionPlanId: number,
  positionId: number,
  options?: { force?: boolean },
) {
  const { data } = await apiClient.post<ApprovePositionResponse>(
    `/production-plans/${productionPlanId}/positions/${positionId}/approve`,
    undefined,
    {
      params: options?.force ? { force: true } : undefined,
    },
  );
  return data;
}

export async function createPlanReleaseBatch(productionPlanId: number, payload: CreatePlanReleaseBatchInput) {
  const { data } = await apiClient.post<ReleaseBatchSummary>(`/production-plans/${productionPlanId}/release-batches`, payload);
  return data;
}

export type PlanFileInfo = {
  batch_id: number;
  file_id: number;
  filename: string;
  extension: string;
  size_bytes: number;
  sheet_name: string;
  total_rows: number;
  parsed_rows: number;
  status: string;
  created_at: string;
};

export type PlanPositionOut = {
  id: number;
  production_plan_id: number;
  source_sku: string;
  source_name: string | null;
  quantity: string;
  status: string;
  validation_status: string;
  errors: string[];
  warnings: string[];
  source_row_number: number | null;
  source_row_numbers?: number[] | null;
  source_ref?: string | null;
  product_id: number | null;
  route_id: number | null;
  route_profile_id: number | null;
  route_name: string | null;
  route_source: string | null;
  route_origin: string | null;
  route_match_quality: string | null;
  route_match_reason: string | null;
  route_assigned_at: string | null;
  route_manual_confirmed_at: string | null;
  route_error: string | null;
  raw_excel_row: Record<string, unknown> | null;
  payload?: Record<string, unknown> | null;
};

export async function planFiles(planId: number) {
  const { data } = await apiClient.get<PlanFileInfo[]>(`/production-plans/${planId}/files`);
  return data;
}

export async function allPlanFiles() {
  const { data } = await apiClient.get<PlanFileInfo[]>("/production-plans/all-files");
  return data;
}

export async function allPlanPositions() {
  const { data } = await apiClient.get<PlanPositionOut[]>("/production-plans/all-positions");
  return data;
}

export async function cancelledPositions() {
  const { data } = await apiClient.get<PlanPositionOut[]>("/production-plans/cancelled-positions");
  return data;
}

export async function cancelPosition(planId: number, positionId: number) {
  const { data } = await apiClient.post(`/production-plans/${planId}/positions/${positionId}/cancel`);
  return data;
}

export async function allPositions(planId: number) {
  const { data } = await apiClient.get<PlanPositionOut[]>(`/production-plans/${planId}/all-positions`);
  return data;
}

export type PlanDuplicateGroup = {
  source_fingerprint: string;
  positions: {
    id: number;
    source_sku: string;
    source_name: string | null;
    quantity: string;
    source_row_number: number | null;
    status: string;
    validation_errors: string[];
    source_fingerprint?: string | null;
    source_row_hash?: string | null;
  }[];
};

export async function getPlanDuplicates(planId: number) {
  const { data } = await apiClient.get<PlanDuplicateGroup[]>(`/production-plans/${planId}/duplicates`);
  return data;
}

export type RouteCheckSection = { id: number; code: string | null; name: string | null };
export type RouteCheckCandidate = {
  route_id: number;
  route_name: string;
  section_ids: number[];
  section_codes: string[];
  missing_required_section_ids: number[];
  excluded_present_section_ids: number[];
  extra_controlled_sections_count: number;
  matched: boolean;
};

export type RouteCheckConditionDiagnostic = {
  source: "excel" | "payload" | "product" | string;
  field_path: string;
  operator: string;
  expected: unknown;
  actual: unknown;
  matched: boolean;
  resolved_by?: string | null;
  excel_column_index?: number | null;
  excel_column_letter?: string | null;
  excel_header?: string | null;
  excel_actual_column_index?: number | null;
  excel_actual_column_letter?: string | null;
  excel_actual_header?: string | null;
  excel_header_match?: boolean | null;
  issues?: string[];
};

export type RouteCheckResponse = {
  expected_signature: {
    template_id: number | null;
    rule_profile_id: number | null;
    matched_rule_ids: number[];
    required_sections: RouteCheckSection[];
    excluded_sections: RouteCheckSection[];
    candidate_routes: RouteCheckCandidate[];
    selected_route_id: number | null;
    route_match_reason: string | null;
    condition_diagnostics?: RouteCheckConditionDiagnostic[];
    excel_column_diagnostics?: RouteCheckConditionDiagnostic[];
  };
  active_route_snapshot: {
    route_id: number;
    route_name: string;
    route_source: string;
    steps: { sequence: number; section_id: number; section_code: string; section_name: string; section_kind: string; operation_name: string }[];
    diagnostic?: {
      error: string | null;
      template_id: number | null;
      rule_profile_id: number | null;
      matched_rule_ids: number[];
      required_sections: RouteCheckSection[];
      excluded_sections: RouteCheckSection[];
      candidate_routes: RouteCheckCandidate[];
      selected_route_id: number | null;
      route_match_reason: string | null;
      condition_diagnostics?: RouteCheckConditionDiagnostic[];
      excel_column_diagnostics?: RouteCheckConditionDiagnostic[];
    };
  } | null;
  match: boolean;
  issues: string[];
};

export async function routeCheck(planId: number, positionId: number) {
  const { data } = await apiClient.get<RouteCheckResponse>(`/production-plans/${planId}/positions/${positionId}/route-check`);
  return data;
}

export type SectionTotalsLine = {
  section_id: number;
  section_code: string;
  section_name: string;
  section_kind: string | null;
  positions_count: number;
  planned_input_quantity: string;
  planned_output_quantity: string;
};

export type SectionTotalsResponse = {
  production_plan_id: number;
  totals: SectionTotalsLine[];
};

export async function sectionTotals(planId: number) {
  const { data } = await apiClient.get<SectionTotalsResponse>(`/production-plans/${planId}/section-totals`);
  return data;
}

export async function batchAssignRoute(planId: number, positionIds: number[], routeId: number | null) {
  const { data } = await apiClient.post(`/production-plans/${planId}/positions/batch-assign-route`, {
    position_ids: positionIds,
    route_id: routeId,
  });
  return data as { updated_count: number; route_id: number | null; route_name: string | null };
}

export async function deleteImportBatch(planId: number, batchId: number) {
  const { data } = await apiClient.delete(`/production-plans/${planId}/batches/${batchId}`);
  return data as { deleted: boolean; batch_id: number };
}

export async function batchAssignRouteGlobal(positionIds: number[], routeId: number | null) {
  const { data } = await apiClient.post(`/production-plans/positions/batch-assign-route`, {
    position_ids: positionIds,
    route_id: routeId,
  });
  return data as { updated_count: number; route_id: number | null; route_name: string | null };
}

export type ProductionPlanningRow = {
  plan_position_id: number;
  production_plan_id: number;
  source_row_number: number | null;
  source_sku: string;
  source_name: string | null;
  quantity: number;
  position_status: string;
  validation_status: string;
  route_id: number | null;
  route_name: string | null;
  route_source: string | null;
  route_origin: string | null;
  route_match_quality: string | null;
  route_match_reason: string | null;
  route_assigned_at: string | null;
  route_manual_confirmed_at: string | null;
  route_error: string | null;
  is_released: boolean;
  has_tasks: boolean;
  is_completed: boolean;
  current_stage_section_id: number | null;
  current_stage_sequence: number | null;
  current_stage_operation: string | null;
  current_stage_section_code: string | null;
  current_stage_section_name: string | null;
  current_stage_task_status: string | null;
  route_steps?: {
    section_id: number;
    section_icon: string | null;
    section_icon_color: string | null;
    sequence: number;
  }[];
};

export type ProductionPlanningRouteSnapshotStep = {
  route_step_id: number;
  sequence: number;
  section_id: number;
  section_code: string;
  section_name: string;
  section_kind: string | null;
  section_icon: string | null;
  section_icon_color: string | null;
  operation_code: string | null;
  operation_name: string;
};

export type ProductionPlanningStage = {
  flow_events: {
    step: string;
    label: string;
    quantity: number;
    event_at: string | null;
    task_id: number | null;
    transfer_id: number | null;
    manual_route_pass?: boolean;
  }[];
  route_step_id: number;
  section_id: number;
  section_code: string;
  section_name: string;
  section_icon: string | null;
  section_icon_color: string | null;
  sequence: number;
  operation_code: string | null;
  operation_name: string;
  planned_quantity: number;
  completed_quantity: number;
  transferred_quantity: number;
  rejected_quantity: number;
  execution_percent: number;
  transfer_percent: number;
  reject_percent: number;
  task_status: string;
  not_started: boolean;
  issued_qty: number;
  issued_last_at: string | null;
  accounted_good_qty: number;
  accounted_reject_qty: number;
  accounted_total_qty: number;
  accounted_last_at: string | null;
  sent_qty: number;
  sent_last_at: string | null;
  accepted_by_next_qty: number;
  accepted_by_next_last_at: string | null;
};

export type ProductionPlanningRowDetail = {
  plan_position_id: number;
  production_plan_id: number;
  source_row_number: number | null;
  source_sku: string;
  source_name: string | null;
  quantity: number;
  position_status: string;
  validation_status: string;
  route_id: number | null;
  route_name: string | null;
  route_source: string | null;
  route_origin: string | null;
  route_match_quality: string | null;
  route_match_reason: string | null;
  route_assigned_at: string | null;
  route_manual_confirmed_at: string | null;
  route_error: string | null;
  is_released: boolean;
  has_tasks: boolean;
  not_started: boolean;
  current_stage_section_id: number | null;
  current_stage_sequence: number | null;
  current_stage_operation: string | null;
  current_stage_section_code: string | null;
  current_stage_section_name: string | null;
  current_stage_task_status: string | null;
  route_snapshot: {
    route_id: number;
    route_name: string | null;
    route_source: string;
    route_origin?: string | null;
    route_match_quality?: string | null;
    route_match_reason?: string | null;
    route_assigned_at?: string | null;
    route_manual_confirmed_at?: string | null;
    steps: ProductionPlanningRouteSnapshotStep[];
  } | null;
  stages: ProductionPlanningStage[];
  raw_excel_row: Record<string, unknown> | null;
  payload?: Record<string, unknown> | null;
};

export async function listProductionPlanningRows() {
  const { data } = await apiClient.get<ProductionPlanningRow[]>("/production-planning/rows");
  return data;
}

export async function getProductionPlanningRowDetail(positionId: number) {
  const { data } = await apiClient.get<ProductionPlanningRowDetail>(`/production-planning/rows/${positionId}`);
  return data;
}

export type WorkTaskOut = {
  id: number;
  route_step_id: number;
  operation_name: string | null;
  operation_code: string | null;
  status: string;
  planned_quantity: number;
  completed_quantity: number;
  sequence: number;
};

export type PositionProgressOut = {
  total_steps: number;
  completed_steps: number;
  percent: number;
};

export type PlanningPositionOut = {
  plan_position_id: number;
  production_plan_id: number;
  source_row_number: number | null;
  source_sku: string;
  source_name: string | null;
  quantity: number;
  route_id: number | null;
  route_name: string | null;
  route_source: string | null;
  status: string;
  progress: PositionProgressOut;
  work_tasks: WorkTaskOut[];
};

export type PlanningSectionOut = {
  section_id: number;
  section_code: string;
  section_name: string;
  section_kind: string;
  positions_count: number;
  ready_count: number;
  in_progress_count: number;
  completed_count: number;
  positions: PlanningPositionOut[];
};

export type ProductionPlanningOverview = {
  sections: PlanningSectionOut[];
};

export async function getProductionPlanningOverview() {
  const { data } = await apiClient.get<ProductionPlanningOverview>("/production-planning/overview");
  return data;
}

export type TakeToWorkResult = {
  position_id: number;
  status: "success" | "already_started" | "failed";
  reason: string | null;
  release_batch_id: number | null;
  internal_plan_id: number | null;
  tasks_created: number | null;
};

export type TakeToWorkResponse = {
  results: TakeToWorkResult[];
};

export type BatchActionStatus = "success" | "failed" | "skipped";

export type BatchActionResult = {
  position_id: number;
  status: BatchActionStatus;
  reason: string | null;
};

export type BatchActionResponse = {
  results: BatchActionResult[];
};

export type CancelBatchRequest = {
  position_ids: number[];
  reason?: string;
};

export type RestoreBatchRequest = {
  position_ids: number[];
  reason?: string;
};

export type ManualPassInput = {
  target_route_step_id?: number;
  complete_route?: boolean;
  comment?: string;
  idempotency_key?: string;
};

export type ManualPassResponse = {
  position_id: number;
  target_route_step_id: number;
  target_task_id: number;
  complete_route: boolean;
  position_completed: boolean;
  tasks_created: number;
  movements_created: number;
  transfers_created: number;
  skipped_stages: number;
};

export type RemainderAllocationItem = {
  remainder_id: number;
  quantity: number;
};

export async function takeToWork(positionIds: number[], remainderAllocation?: RemainderAllocationItem[]) {
  const { data } = await apiClient.post<TakeToWorkResponse>("/production-planning/rows/take-to-work", {
    position_ids: positionIds,
    remainder_allocation: remainderAllocation,
  });
  return data;
}

export type CompletedStage = {
  section_id: number;
  operation_code: string;
  operation_name: string;
  sequence: number;
};

export type AvailableRemainder = {
  id: number;
  remainder_quantity: number;
  original_issued: number;
  created_at: string | null;
  created_by_user_name: string | null;
  completed_stages_json: CompletedStage[];
  max_completed_seq: number;
  max_completed_stage_name: string;
  spg_name: string;
};

export type PreviewRouteStep = {
  sequence: number;
  section_id: number;
  section_name: string;
  section_code: string;
  operation_name: string;
};

export type DefaultAllocationItem = {
  remainder_id: number;
  allocated_quantity: number;
};

export type RemaindersPreviewResponse = {
  position_id: number;
  product_sku: string | null;
  product_name: string | null;
  release_quantity: number;
  route_steps: PreviewRouteStep[];
  available_remainders: AvailableRemainder[];
  default_allocation: DefaultAllocationItem[];
};

export async function getRemaindersPreview(positionId: number): Promise<RemaindersPreviewResponse> {
  const { data } = await apiClient.get<RemaindersPreviewResponse>(
    `/production-planning/rows/${positionId}/remainders-preview`
  );
  return data;
}


export async function manualPassToStage(positionId: number, payload: ManualPassInput) {
  const { data } = await apiClient.post<ManualPassResponse>(`/production-planning/rows/${positionId}/manual-pass`, payload);
  return data;
}

export async function cancelPositionExecution(positionId: number) {
  const { data } = await apiClient.post(`/production-planning/rows/${positionId}/cancel`);
  return data;
}

export async function cancelPositionsExecutionBatch(payload: CancelBatchRequest) {
  const { data } = await apiClient.post<BatchActionResponse>("/production-planning/rows/cancel-batch", payload);
  return data;
}

export async function restorePositionExecution(positionId: number, reason?: string) {
  const { data } = await apiClient.post(`/production-planning/rows/${positionId}/restore`, { reason });
  return data;
}

export async function restorePositionsExecutionBatch(payload: RestoreBatchRequest) {
  const { data } = await apiClient.post<BatchActionResponse>("/production-planning/rows/restore-batch", payload);
  return data;
}

export async function restorePosition(planId: number, positionId: number, reason?: string) {
  const { data } = await apiClient.post(`/production-plans/${planId}/positions/${positionId}/restore`, { reason });
  return data;
}

export async function softDeleteCancelledPosition(planId: number, positionId: number, reason?: string) {
  const { data } = await apiClient.delete(`/production-plans/${planId}/positions/${positionId}`, {
    data: { reason },
  });
  return data;
}

export type UpdatePositionQuantityInput = {
  quantity: number | string;
  quantity_per_hanger?: number | null;
};

export async function updatePositionQuantity(
  planId: number,
  positionId: number,
  payload: UpdatePositionQuantityInput,
) {
  const { data } = await apiClient.patch<PlanPositionOut>(
    `/production-plans/${planId}/positions/${positionId}/quantity`,
    payload,
  );
  return data;
}

export type StatusHistoryEntry = {
  id: number;
  from_status: string;
  to_status: string;
  changed_by: number | null;
  changed_at: string;
  reason: string | null;
};

export async function getPositionHistory(planId: number, positionId: number) {
  const { data } = await apiClient.get<StatusHistoryEntry[]>(`/production-plans/${planId}/positions/${positionId}/history`);
  return data;
}

export async function resetAllPlans() {
  await apiClient.post("/production-plans/reset-all");
}

// --- Bulk action schemas (shared with backend BulkActionResponse) ----------

export type BulkActionStatus = "success" | "failed" | "skipped";

export type BulkActionResult<TMeta = Record<string, unknown>> = {
  id: number;
  status: BulkActionStatus;
  reason: string | null;
  meta?: TMeta | null;
};

export type BulkActionResponse<TMeta = Record<string, unknown>> = {
  results: BulkActionResult<TMeta>[];
};

export type BulkActionRequest = {
  ids: number[];
  reason?: string | null;
  force?: boolean;
};

export type SoftDeleteExecutionRequest = {
  position_ids: number[];
  reason?: string | null;
};

export type ManualPassExecutionRequest = {
  position_ids: number[];
  target_route_stage_id?: number | null;
  complete_route?: boolean;
  comment?: string | null;
  idempotency_key?: string | null;
};

export type ManualPassExecutionResult = {
  position_id: number;
  status: BulkActionStatus;
  reason: string | null;
  movements_created?: number | null;
  transfers_created?: number | null;
  tasks_created?: number | null;
  position_completed?: boolean | null;
};

export type ManualPassExecutionResponse = {
  results: ManualPassExecutionResult[];
};

export async function bulkApprovePositions(
  planId: number,
  ids: number[],
  force = false,
): Promise<BulkActionResponse> {
  const { data } = await apiClient.post<BulkActionResponse>(
    `/production-plans/${planId}/positions/bulk-approve`,
    { ids, force },
  );
  return data;
}

export async function bulkDeletePositions(
  planId: number,
  ids: number[],
  reason?: string,
): Promise<BulkActionResponse> {
  const { data } = await apiClient.post<BulkActionResponse>(
    `/production-plans/${planId}/positions/bulk-delete`,
    { ids, reason },
  );
  return data;
}

export async function softDeletePositionsExecutionBatch(
  payload: SoftDeleteExecutionRequest,
): Promise<BatchActionResponse> {
  const { data } = await apiClient.post<BatchActionResponse>(
    "/production-planning/rows/soft-delete-batch",
    payload,
  );
  return data;
}

export async function manualPassPositionsExecutionBatch(
  payload: ManualPassExecutionRequest,
): Promise<ManualPassExecutionResponse> {
  const { data } = await apiClient.post<ManualPassExecutionResponse>(
    "/production-planning/rows/manual-pass-batch",
    payload,
  );
  return data;
}

export type ProductWipRemainder = {
  spg_id: number;
  spg_code: string;
  spg_name: string;
  completed_ops: string;
  spg_icon: string | null;
  spg_icon_color: string | null;
  quantity: number;
};

export type ProductWipTask = {
  section_id: number;
  section_code: string;
  section_name: string;
  operation_name: string;
  section_icon: string | null;
  section_icon_color: string | null;
  planned_qty: number;
  completed_qty: number;
  in_work_qty: number;
  active_tasks_count: number;
};

export type ProductWipStats = {
  sku: string;
  product_name: string;
  product_id: number | null;
  remainders: ProductWipRemainder[];
  in_work: ProductWipTask[];
};

export async function getProductWipStats(sku: string) {
  const { data } = await apiClient.get<ProductWipStats>(`/production-planning/product-wip-stats/${encodeURIComponent(sku)}`);
  return data;
}
