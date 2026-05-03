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
