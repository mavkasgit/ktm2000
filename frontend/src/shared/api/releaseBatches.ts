import { apiClient } from "./client";
import type { ReleaseBatchSummary } from "./productionPlans";

export async function getReleaseBatch(releaseBatchId: number) {
  const { data } = await apiClient.get<ReleaseBatchSummary>(`/release-batches/${releaseBatchId}`);
  return data;
}

export async function releaseBatch(releaseBatchId: number) {
  const { data } = await apiClient.post<ReleaseBatchSummary>(`/release-batches/${releaseBatchId}/release`);
  return data;
}
