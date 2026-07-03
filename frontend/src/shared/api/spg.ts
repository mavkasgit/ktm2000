import { apiClient } from "./client";

export type SpgSectionOut = {
  section_id: number;
  section_code: string;
  section_name: string;
  sort_order: number;
  kind: string;
  icon: string | null;
  icon_color: string | null;
};

export type SpgOut = {
  id: number;
  code: string;
  name: string;
  description: string | null;
  sort_order: number;
  is_active: boolean;
  icon: string | null;
  icon_color: string | null;
  sections: SpgSectionOut[];
};

export type SpgSnapshotSection = {
  id: number;
  code: string;
  name: string;
  icon: string | null;
  icon_color: string | null;
};

export type SpgSnapshotPerSection = {
  planned: number;
  completed: number;
  available: number;
  issued: number;
  transferred: number;
  received: number;
  remainder: number;
};

export type SpgSnapshotRow = {
  product_id: number;
  sku: string;
  product_name: string;
  planned_total: number;
  completed_total: number;
  issued_total: number;
  remainder_total: number;
  spg_available: number;
  completion_pct: number;
  current_section: string | null;
  negative_remainder_count: number;
  per_section: Record<string, SpgSnapshotPerSection>;
};

export type SpgSnapshotTotals = {
  planned: number;
  completed: number;
  issued: number;
  remainders: number;
  spg_available: number;
  negative_total: number;
  negative_remainder_count: number;
};

export type SpgSnapshotResponse = {
  spg_id: number;
  spg_code: string;
  spg_name: string;
  sections: SpgSnapshotSection[];
  rows: SpgSnapshotRow[];
  totals: SpgSnapshotTotals;
};

export async function getSpgList(): Promise<SpgOut[]> {
  const { data } = await apiClient.get<SpgOut[]>("/spg");
  return data;
}

export type SpgPatchInput = {
  name?: string;
  description?: string | null;
  sort_order?: number;
  is_active?: boolean;
  icon?: string | null;
  icon_color?: string | null;
  section_ids?: number[];
};

export async function patchSpg(id: number, payload: SpgPatchInput): Promise<SpgOut> {
  const { data } = await apiClient.patch<SpgOut>(`/spg/${id}`, payload);
  return data;
}

export async function deleteSpg(id: number): Promise<void> {
  await apiClient.delete(`/spg/${id}`);
}

export async function getSpgSnapshot(spgId: number): Promise<SpgSnapshotResponse> {
  const { data } = await apiClient.get<SpgSnapshotResponse>(`/spg/${spgId}/snapshot`);
  return data;
}


