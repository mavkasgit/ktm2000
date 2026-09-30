import type { PlanFileInfo } from "@/shared/api/productionPlans";

function timestamp(value: string | null | undefined): number | null {
  if (!value) return null;
  const parsed = Date.parse(value);
  return Number.isNaN(parsed) ? null : parsed;
}

/**
 * Последний применённый батч **каждого** плана (#172): откат — LIFO, поэтому
 * ориентир — `applied_at`, а не порядок загрузки (`created_at` батча) и не
 * audit_logs. Карта, а не одно число: список файлов приходит по всем планам
 * сразу, и на странице истории импортов батчи разных планов лежат в одной
 * таблице — «последний» у каждого плана свой. Глобальный LIFO погасил бы
 * откат у всех планов, кроме одного.
 *
 * Равные `applied_at` — выигрывает первый: порядок внутри одной метки времени
 * неразличим, а LIFO не должен зависеть от порядка строк в ответе.
 */
export function lastAppliedBatchIdByPlan(files: PlanFileInfo[]): Map<number, number> {
  const lastAppliedAtByPlan = new Map<number, number>();
  const lastBatchIdByPlan = new Map<number, number>();
  for (const file of files) {
    const appliedAt = timestamp(file.applied_at);
    if (appliedAt === null) continue;
    const previous = lastAppliedAtByPlan.get(file.production_plan_id);
    if (previous !== undefined && previous >= appliedAt) continue;
    lastAppliedAtByPlan.set(file.production_plan_id, appliedAt);
    lastBatchIdByPlan.set(file.production_plan_id, file.batch_id);
  }
  return lastBatchIdByPlan;
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
