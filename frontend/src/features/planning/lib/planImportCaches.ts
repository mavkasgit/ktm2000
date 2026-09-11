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
