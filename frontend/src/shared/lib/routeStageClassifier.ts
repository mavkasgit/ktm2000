// Helpers for distinguishing storage/transit nodes from production stages
// in route UI components.
//
// Mirrors the backend `app.services.route_storage_classifier` module — keep
// both in sync when adding new stage kinds or section types.

export type RouteStageKind = "production" | "transit";
export type StorageType = "raw_stock" | "wip_stock" | "finished_stock" | "scrap" | "quarantine";

export const STORAGE_TYPES: readonly StorageType[] = [
  "raw_stock",
  "wip_stock",
  "finished_stock",
  "scrap",
  "quarantine",
] as const;

export function isStorageType(type: string | null | undefined): boolean {
  return STORAGE_TYPES.includes(type as StorageType);
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
  section: { type?: string | null } | null | undefined,
): SectionRole {
  return isStorageType(section?.type) ? "storage" : "production";
}
