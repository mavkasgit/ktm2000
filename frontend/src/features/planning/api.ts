import {
  applyProductionPlanChangeSet,
  approveProductionPlanPosition,
  createPlanReleaseBatch,
  discardProductionPlanChangeSet,
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
    normalizeHangerQuantity?: boolean;
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
    normalize_hanger_quantity: options?.normalizeHangerQuantity ?? true,
  })
  lastImport = enrichImport(payload as Record<string, any>)
  return lastImport
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

export async function applyChangeSet(
  planId?: string,
  changeSetId?: string,
  options?: { skipInvalid?: boolean },
) {
  const resolvedPlanId = planId || lastImport?.production_plan_id
  const resolvedChangeSetId = changeSetId || lastImport?.change_set_id
  if (!resolvedPlanId || !resolvedChangeSetId) {
    throw new Error("Нет production_plan_id или change_set_id")
  }
  const payload = await applyProductionPlanChangeSet(
    Number(resolvedPlanId),
    Number(resolvedChangeSetId),
    { skipInvalid: options?.skipInvalid },
  )
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
  await discardProductionPlanChangeSet(Number(planId), Number(changeSetId))
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
