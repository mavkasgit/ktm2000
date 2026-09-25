import type { QueryClient } from "@tanstack/react-query";

import { queryKeys } from "@/shared/api/queryKeys";

/**
 * Инвалидация доменов, зависящих от состава плана: применение/откат импорта
 * меняет позиции плана, участки, ГХП и превью (#172).
 */
export function invalidatePlanImportCaches(
  queryClient: QueryClient,
  params: { planId: string | number; batchId?: number | null },
): void {
  void queryClient.invalidateQueries({ queryKey: queryKeys.plan.allFiles() });
  void queryClient.invalidateQueries({ queryKey: queryKeys.plan.allPositions() });
  void queryClient.invalidateQueries({ queryKey: queryKeys.plan.preview(params.planId) });
  void queryClient.invalidateQueries({ queryKey: queryKeys.shopfloor.boardAll() });
  void queryClient.invalidateQueries({ queryKey: queryKeys.sections.all() });
  void queryClient.invalidateQueries({ queryKey: queryKeys.spg.snapshotAll() });
  if (params.batchId != null) {
    void queryClient.invalidateQueries({ queryKey: queryKeys.plan.batchPreview(params.batchId) });
  }
}

/** Полное удаление плана сохраняет каталоги, но меняет все производственные домены. */
export function invalidatePlanDeletionCaches(
  queryClient: QueryClient,
  planId: string | number,
): void {
  const keys = [
    queryKeys.execution.plans(),
    queryKeys.execution.rows(),
    queryKeys.execution.rowDetailAll(),
    queryKeys.plan.allFiles(),
    queryKeys.plan.allPositions(),
    queryKeys.plan.duplicates(),
    queryKeys.plan.preview(planId),
    queryKeys.plan.previewPage(planId),
    queryKeys.plan.positionDetailAll(),
    queryKeys.plan.deletePreview(planId),
    queryKeys.dailyPlans.all(),
    queryKeys.shopfloor.boardAll(),
    queryKeys.shopfloor.statsAll(),
    queryKeys.shopfloor.summary(),
    queryKeys.shopfloor.incomingTransfersAll(),
    queryKeys.transfers.readyAll(),
    queryKeys.transfers.historyAll(),
    queryKeys.spg.snapshotAll(),
    queryKeys.spg.defectsAll(),
    queryKeys.stock.balancesAll(),
    queryKeys.stock.transactions(),
    queryKeys.auditLogs.list(),
    queryKeys.actions.all,
  ] as const;
  for (const queryKey of keys) {
    void queryClient.invalidateQueries({ queryKey });
  }
}
