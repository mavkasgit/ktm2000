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

export async function seedSections() {
  const { data } = await apiClient.post<Section[]>("/sections-seed");
  return data;
}
