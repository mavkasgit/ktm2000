import { getErrorMessage } from "@/shared/api/client";
import type { BulkId } from "./selection";

export type BulkActionStatus = "success" | "failed" | "skipped";

export interface BulkActionResultItem<TId extends BulkId> {
  id: TId;
  status: BulkActionStatus;
  reason?: string | null;
  label?: string;
  meta?: Record<string, unknown>;
}

export interface BulkActionSummary {
  total: number;
  success: number;
  failed: number;
  skipped: number;
}

export interface BulkRunnerProgress {
  total: number;
  completed: number;
  running: boolean;
}

export interface BulkActionDefinition<TId extends BulkId, TContext = void> {
  id: string;
  label: string;
  primaryLabel?: string;
  pendingLabel?: string;
  emptyLabel?: string;
  isEligible?: (id: TId, context: TContext) => boolean;
  getIneligibleReason?: (id: TId, context: TContext) => string | null | undefined;
  run: (ids: TId[], context: TContext) => Promise<BulkActionResultItem<TId>[]>;
}

export function summarizeBulkResults<TId extends BulkId>(results: BulkActionResultItem<TId>[]): BulkActionSummary {
  return results.reduce<BulkActionSummary>(
    (summary, result) => {
      summary.total += 1;
      summary[result.status] += 1;
      return summary;
    },
    { total: 0, success: 0, failed: 0, skipped: 0 },
  );
}

export function normalizeBulkError(error: unknown): string {
  return getErrorMessage(error);
}

export async function runBulkAction<TId extends BulkId, TContext>(
  action: BulkActionDefinition<TId, TContext>,
  ids: Iterable<TId>,
  context: TContext,
  onProgress?: (progress: BulkRunnerProgress) => void,
): Promise<BulkActionResultItem<TId>[]> {
  const selectedIds = Array.from(ids);
  const skipped = selectedIds
    .filter((id) => action.isEligible && !action.isEligible(id, context))
    .map<BulkActionResultItem<TId>>((id) => ({
      id,
      status: "skipped",
      reason: action.getIneligibleReason?.(id, context) ?? "Недоступно для выбранного действия",
    }));
  const executableIds = selectedIds.filter((id) => !action.isEligible || action.isEligible(id, context));

  onProgress?.({ total: selectedIds.length, completed: skipped.length, running: executableIds.length > 0 });
  if (executableIds.length === 0) {
    onProgress?.({ total: selectedIds.length, completed: selectedIds.length, running: false });
    return skipped;
  }

  try {
    const results = await action.run(executableIds, context);
    const completed = skipped.length + results.length;
    onProgress?.({ total: selectedIds.length, completed, running: false });
    return [...skipped, ...results];
  } catch (error) {
    const reason = normalizeBulkError(error);
    const failed = executableIds.map<BulkActionResultItem<TId>>((id) => ({ id, status: "failed", reason }));
    onProgress?.({ total: selectedIds.length, completed: selectedIds.length, running: false });
    return [...skipped, ...failed];
  }
}
