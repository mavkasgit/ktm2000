import type { QueryClient } from "@tanstack/react-query";

import { invalidateAfter } from "@/shared/api/cacheInvalidation";
import { queryKeys } from "@/shared/api/queryKeys";

/**
 * Сброс кэша после применения/отката импорта плана (#172).
 *
 * Домены (план, контроль выполнения, цех, участки, ГХП, справочник артикулов)
 * перечислены в реестре `CACHE_ACTIONS.importApplied` — повторять их здесь нельзя,
 * иначе список снова разойдётся с матрицей. Локально остаются только ключи,
 * параметризованные конкретным планом/батчем: они описывают предпросмотр одного
 * загруженного файла, а не домен данных, и сбрасываются точечно.
 */
export function invalidatePlanImportCaches(
  queryClient: QueryClient,
  params: { planId: string | number; batchId?: number | null },
): void {
  void invalidateAfter(queryClient, "importApplied");
  void queryClient.invalidateQueries({ queryKey: queryKeys.plan.preview(params.planId) });
  if (params.batchId != null) {
    void queryClient.invalidateQueries({ queryKey: queryKeys.plan.batchPreview(params.batchId) });
  }
}
