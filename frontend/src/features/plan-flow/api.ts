import {
  applyProductionPlanChangeSet,
  approveProductionPlanPosition,
  createPlanReleaseBatch,
  importExcel,
  previewProductionPlan as loadProductionPlanPreview,
  releaseBatch as releaseReleaseBatch,
} from "shared/api"

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

export async function uploadExcel(file: File) {
  const payload = await importExcel({ file })
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

export async function applyChangeSet() {
  if (!lastImport?.production_plan_id || !lastImport?.change_set_id) {
    throw new Error("Нет production_plan_id или change_set_id")
  }
  const payload = await applyProductionPlanChangeSet(Number(lastImport.production_plan_id), Number(lastImport.change_set_id))
  return {
    ...payload,
    planId: String((payload as Record<string, any>).production_plan_id ?? lastImport.production_plan_id),
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
