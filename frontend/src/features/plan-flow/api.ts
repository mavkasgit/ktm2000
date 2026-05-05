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
  options?: { templateId?: number; columnMapping?: Record<string, string>; productionPlanId?: number },
) {
  const payload = await importExcel({
    file,
    template_id: options?.templateId,
    column_mapping: options?.columnMapping,
    mode: "append_to_plan",
    production_plan_id: options?.productionPlanId ?? undefined,
  })
  lastImport = enrichImport(payload as Record<string, any>)
  return lastImport
}

export async function uploadTestExcel(productionPlanId?: number) {
  const { data } = await apiClient.post("/imports/excel/test", undefined, {
    params: { production_plan_id: productionPlanId },
  })
  lastImport = enrichImport(data as Record<string, any>)
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
