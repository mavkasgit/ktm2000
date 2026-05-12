import {
  applyProductionPlanChangeSet,
  approveProductionPlanPosition,
  createPlanReleaseBatch,
  importExcel,
  previewProductionPlan as loadProductionPlanPreview,
  releaseBatch as releaseReleaseBatch,
  rollbackProductionPlanChangeSet,
} from "shared/api"
import { apiClient } from "shared/api/client"

let lastImport: Record<string, any> | null = null

function enrichImport(payload: Record<string, any>) {
  return {
    ...payload,
    importId: String(payload.import_batch_id ?? ""),
    changeSetId: String(payload.change_set_id ?? ""),
    planId: String(payload.production_plan_id ?? ""),
    rows: payload.items ?? [],
  }
}

export async function uploadExcel(
  file: File,
  options?: {
    templateId?: number;
    columnMapping?: Record<string, string>;
    productionPlanId?: number;
    planMonth?: string;
    planVersion?: string;
    rowSelection?: string;
    sheetIndex?: number;
  },
) {
  const payload = await importExcel({
    file,
    sheet_index: options?.sheetIndex ?? 0,
    template_id: options?.templateId,
    column_mapping: options?.columnMapping,
    mode: options?.productionPlanId ? "append_to_plan" : "create_plan",
    production_plan_id: options?.productionPlanId ?? undefined,
    plan_month: options?.planMonth?.trim() || undefined,
    plan_version: options?.planVersion?.trim() || undefined,
    row_selection: options?.rowSelection?.trim() || undefined,
  })
  lastImport = enrichImport(payload as Record<string, any>)
  return lastImport
}

export async function uploadTestExcel(options?: {
  productionPlanId?: number;
  techcardId?: number;
  runId?: string;
  planMonth?: string;
  planVersion?: string;
  quantity?: number;
}) {
  const { data } = await apiClient.post("/imports/excel/test", undefined, {
    params: {
      production_plan_id: options?.productionPlanId,
      techcard_id: options?.techcardId,
      run_id: options?.runId?.trim() || undefined,
      plan_month: options?.planMonth?.trim() || undefined,
      plan_version: options?.planVersion?.trim() || undefined,
      quantity: options?.quantity,
    },
  })
  lastImport = enrichImport(data as Record<string, any>)
  return lastImport
}

export type DemoStageResult = {
  section_id: number;
  section_code: string;
  task_id: number;
  input_qty: string;
  defect_percent: number;
  defect_qty: string;
  good_qty: string;
  performed_at: string;
  accounted_at: string;
};

export type DemoFullRouteResponse = {
  run_id: string;
  production_plan_id: number;
  plan_position_id: number;
  internal_plan_id: number | null;
  route_id: number;
  tasks_created: number;
  stage_preset: string;
  stopped_at_stage: string;
  stage_results: DemoStageResult[];
  execution_row_url: string;
  shopfloor_section_urls: string[];
};

export async function runDemoFullRoute(payload: {
  initial_quantity: number;
  techcard_id: number;
  route_id?: number;
  route_name?: string;
  scenario_id?: string;
  run_id?: string;
  start_performed_at?: string;
  plan_month?: string;
  plan_version?: string;
  production_plan_id?: number;
  stage_preset?: string;
  target_route_step_id?: number | null;
}) {
  const { data } = await apiClient.post<DemoFullRouteResponse>("/demo/test-runs/full-route", payload);
  return data;
}

export async function previewDiff() {
  if (!lastImport) {
    throw new Error("Сначала загрузите Excel")
  }
  return {
    ...lastImport,
    rows: lastImport.items ?? [],
  }
}

export async function applyChangeSet(planId?: string, changeSetId?: string) {
  const resolvedPlanId = planId || lastImport?.production_plan_id
  const resolvedChangeSetId = changeSetId || lastImport?.change_set_id
  if (!resolvedPlanId || !resolvedChangeSetId) {
    throw new Error("Нет production_plan_id или change_set_id")
  }
  const payload = await applyProductionPlanChangeSet(Number(resolvedPlanId), Number(resolvedChangeSetId))
  return {
    ...payload,
    planId: String((payload as Record<string, any>).production_plan_id ?? resolvedPlanId),
  }
}

export async function rollbackChangeSet(planId: string, changeSetId: string) {
  const payload = await rollbackProductionPlanChangeSet(Number(planId), Number(changeSetId))
  return {
    ...payload,
    planId: String((payload as Record<string, any>).production_plan_id ?? planId),
  }
}

export async function discardImport(planId: string, changeSetId: string) {
  try {
    await rollbackChangeSet(planId, changeSetId)
  } catch {
    // ignore rollback errors on discard
  }
}

export async function previewProductionPlan(planId?: string) {
  const resolvedPlanId = Number(planId || lastImport?.production_plan_id)
  if (!resolvedPlanId) {
    throw new Error("Нет production_plan_id")
  }
  const payload = await loadProductionPlanPreview(resolvedPlanId)
  return {
    ...payload,
    planId: String((payload as Record<string, any>).production_plan_id ?? resolvedPlanId),
  }
}

export async function approvePositions(planId: string, positionIds: string[]) {
  const results = []
  for (const positionId of positionIds) {
    results.push(await approveProductionPlanPosition(Number(planId), Number(positionId)))
  }
  return { approvalId: `${planId}:${positionIds.join(",")}`, results }
}

export async function createReleaseBatch(planId: string) {
  const payload = await createPlanReleaseBatch(Number(planId), { batch_type: "manual" })
  return {
    ...payload,
    releaseBatchId: String((payload as Record<string, any>).id ?? ""),
  }
}

export async function releaseBatch(releaseBatchId: string) {
  const payload = await releaseReleaseBatch(Number(releaseBatchId))
  return {
    ...payload,
    releaseJobId: String((payload as Record<string, any>).internal_plan_id ?? (payload as Record<string, any>).id ?? ""),
  }
}
