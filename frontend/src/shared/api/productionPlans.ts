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

export async function applyProductionPlanChangeSet(productionPlanId: number, changeSetId: number) {
  const { data } = await apiClient.post<ProductionPlanPreview>(
    `/production-plans/${productionPlanId}/change-sets/${changeSetId}/apply`,
  );
  return data;
}

export async function rollbackProductionPlanChangeSet(productionPlanId: number, changeSetId: number) {
  const { data } = await apiClient.post<ProductionPlanPreview>(
    `/production-plans/${productionPlanId}/change-sets/${changeSetId}/rollback`,
  );
  return data;
}

export async function approveProductionPlanPosition(productionPlanId: number, positionId: number) {
  const { data } = await apiClient.post<ApprovePositionResponse>(
    `/production-plans/${productionPlanId}/positions/${positionId}/approve`,
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
  product_id: number | null;
  route_id: number | null;
  route_name: string | null;
  route_source: string | null;
  route_error: string | null;
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
  source_sku: string;
  due_date: string | null;
  positions: {
    id: number;
    source_sku: string;
    source_name: string | null;
    quantity: string;
    source_row_number: number | null;
    status: string;
    validation_errors: string[];
  }[];
};

export async function getPlanDuplicates(planId: number) {
  const { data } = await apiClient.get<PlanDuplicateGroup[]>(`/production-plans/${planId}/duplicates`);
  return data;
}

export type RouteCheckStep = { step_id: string; operation_code: string | null; section_kind: string | null; description: string };

export type RouteCheckResponse = {
  expected_signature: {
    steps: RouteCheckStep[];
    primary_operation: string | null;
    output_kind: string | null;
    additional_pack_operations: string[];
  };
  active_route_snapshot: {
    route_id: number;
    route_name: string;
    route_version: string;
    steps: { sequence: number; section_id: number; section_code: string; section_name: string; section_kind: string; operation_name: string }[];
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
  route_error: string | null;
  is_released: boolean;
  has_tasks: boolean;
};

export type ProductionPlanningRouteSnapshotStep = {
  route_step_id: number;
  sequence: number;
  section_id: number;
  section_code: string;
  section_name: string;
  section_kind: string | null;
  operation_code: string | null;
  operation_name: string;
};

export type ProductionPlanningStage = {
  route_step_id: number;
  section_id: number;
  section_code: string;
  section_name: string;
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
  route_error: string | null;
  is_released: boolean;
  has_tasks: boolean;
  not_started: boolean;
  route_snapshot: {
    route_id: number;
    route_name: string | null;
    route_source: string;
    steps: ProductionPlanningRouteSnapshotStep[];
  } | null;
  stages: ProductionPlanningStage[];
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

export async function takeToWork(positionIds: number[]) {
  const { data } = await apiClient.post<TakeToWorkResponse>("/production-planning/rows/take-to-work", {
    position_ids: positionIds,
  });
  return data;
}

export async function cancelPositionExecution(positionId: number) {
  const { data } = await apiClient.post(`/production-planning/rows/${positionId}/cancel`);
  return data;
}

export async function resetAllPlans() {
  await apiClient.post("/production-plans/reset-all");
}
