import type { PlanFileInfo } from "@/shared/api/productionPlans";

function timestamp(value: string | null | undefined): number | null {
  if (!value) return null;
  const parsed = Date.parse(value);
  return Number.isNaN(parsed) ? null : parsed;
}

/**
 * Последний применённый батч плана (#172): откат — LIFO, поэтому ориентир —
 * `applied_at`, а не порядок загрузки (`created_at` батча) и не audit_logs.
 * Файлы в списке приходят по всем планам — план фильтруем явно.
 */
export function findLastAppliedBatchId(files: PlanFileInfo[], planId: number | null | undefined): number | null {
  if (planId == null) return null;
  let lastBatchId: number | null = null;
  let lastAppliedAt = Number.NEGATIVE_INFINITY;
  for (const file of files) {
    if (file.production_plan_id !== planId) continue;
    const appliedAt = timestamp(file.applied_at);
    if (appliedAt === null || appliedAt <= lastAppliedAt) continue;
    lastAppliedAt = appliedAt;
    lastBatchId = file.batch_id;
  }
  return lastBatchId;
}

/**
 * Применённый батч того же плана, применённый позже парсинга этого батча
 * (свежесть не блокирует — предупреждение в диалоге применения).
 */
export function findNewerAppliedBatch(
  files: PlanFileInfo[],
  params: { planId: number | null | undefined; batchId: number | null | undefined; parsedAt: string | null | undefined },
): PlanFileInfo | null {
  const { planId, batchId, parsedAt } = params;
  if (planId == null || batchId == null) return null;
  const parsed = timestamp(parsedAt);
  if (parsed === null) return null;

  let newer: PlanFileInfo | null = null;
  let newerAt = parsed;
  for (const file of files) {
    if (file.production_plan_id !== planId || file.batch_id === batchId) continue;
    const appliedAt = timestamp(file.applied_at);
    if (appliedAt === null || appliedAt <= newerAt) continue;
    newerAt = appliedAt;
    newer = file;
  }
  return newer;
}
