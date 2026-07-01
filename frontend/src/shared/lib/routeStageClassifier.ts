// Helpers for distinguishing storage/transit nodes from production stages
// in route UI components.
//
// Mirrors the backend `app.services.route_storage_classifier` module — keep
// both in sync when adding new stage kinds or section kinds.

export type RouteStageKind = "production" | "transit";
export type StorageKind = "raw_stock" | "wip_stock" | "finished_stock";

export const STORAGE_KINDS: readonly StorageKind[] = [
  "raw_stock",
  "wip_stock",
  "finished_stock",
] as const;

export function isStorageKind(kind: string | null | undefined): boolean {
  return STORAGE_KINDS.includes(kind as StorageKind);
}

export function isTransitStage(stage: {
  stage_kind?: RouteStageKind | string | null;
} | null | undefined): boolean {
  return stage?.stage_kind === "transit";
}

export function isProductionStage(stage: {
  stage_kind?: RouteStageKind | string | null;
  section_id?: number | null;
} | null | undefined): boolean {
  return stage?.stage_kind !== "transit" && typeof stage?.section_id === "number";
}

export type SectionRole = "production" | "storage";

export function classifySectionRole(
  section: { kind?: string | null } | null | undefined,
): SectionRole {
  return isStorageKind(section?.kind) ? "storage" : "production";
}
