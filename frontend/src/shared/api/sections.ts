import { apiClient } from "./client";

export type SectionKind = "production" | "raw_stock" | "wip_stock" | "finished_stock";

export type Section = {
  id: number;
  code: string;
  name: string;
  description: string | null;
  is_active: boolean;
  kind: SectionKind;
  icon: string | null;
  icon_color: string | null;
};

export type CreateSectionInput = {
  code: string;
  name: string;
  description?: string | null;
  is_active?: boolean;
  kind?: SectionKind;
  icon?: string | null;
  icon_color?: string | null;
};

export type PatchSectionInput = Partial<Pick<CreateSectionInput, "name" | "description" | "is_active" | "kind" | "icon" | "icon_color">>;

export async function listSections() {
  const { data } = await apiClient.get<Section[]>("/sections");
  return data;
}

export async function createSection(payload: CreateSectionInput) {
  const { data } = await apiClient.post<Section>("/sections", payload);
  return data;
}

export async function patchSection(sectionId: number, payload: PatchSectionInput) {
  const { data } = await apiClient.patch<Section>(`/sections/${sectionId}`, payload);
  return data;
}

export async function reorderSections(ids: number[]) {
  await apiClient.post("/sections/reorder", { ids });
}

// ─── Operation Groups ────────────────────────────────────────────────────────

export type SectionOperationInfo = {
  id: number;
  operation_code: string;
  operation_name: string;
  is_significant: boolean;
  icon: string | null;
  icon_color: string | null;
  group_code: string | null;
  group_name: string | null;
  sort_order: number;
  resolver_type: string | null;
};

export type OperationGroup = {
  group_code: string | null;
  group_name: string | null;
  sort_order: number;
  operations: SectionOperationInfo[];
};

export type OperationGroupCreateInput = {
  group_code: string;
  group_name: string;
  sort_order?: number;
};

export type OperationGroupUpdateInput = {
  group_name?: string;
  sort_order?: number;
};

export type OperationMoveInput = {
  operation_id: number;
  new_group_code: string;
};

export async function getSectionOperationGroups(sectionId: number) {
  const { data } = await apiClient.get<OperationGroup[]>(
    `/sections/${sectionId}/operation-groups`,
  );
  return data;
}

export async function createOperationGroup(
  sectionId: number,
  payload: OperationGroupCreateInput,
) {
  const { data } = await apiClient.post<OperationGroup>(
    `/sections/${sectionId}/operation-groups`,
    payload,
  );
  return data;
}

export async function updateOperationGroup(
  sectionId: number,
  groupCode: string,
  payload: OperationGroupUpdateInput,
) {
  const { data } = await apiClient.put<OperationGroup>(
    `/sections/${sectionId}/operation-groups/${groupCode}`,
    payload,
  );
  return data;
}

export async function deleteOperationGroup(sectionId: number, groupCode: string) {
  const { data } = await apiClient.delete<{ status: string }>(
    `/sections/${sectionId}/operation-groups/${groupCode}`,
  );
  return data;
}

export async function moveOperation(sectionId: number, payload: OperationMoveInput) {
  await apiClient.put(
    `/sections/${sectionId}/operations/${payload.operation_id}/move`,
    { new_group_code: payload.new_group_code },
  );
}

export type SectionWithOperations = {
  id: number;
  code: string;
  name: string;
  kind: string;
  icon: string | null;
  icon_color: string | null;
  operations: Array<{
    id: number;
    operation_code: string;
    operation_name: string;
    is_significant: boolean;
    group_code: string | null;
    group_name: string | null;
  }>;
};

export async function listSectionsWithOperations(): Promise<SectionWithOperations[]> {
  const { data } = await apiClient.get<SectionWithOperations[]>("/sections/all/operations");
  return data;
}
