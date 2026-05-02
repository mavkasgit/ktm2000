import { apiClient } from "./client";

export type ImportTemplate = {
  id: number;
  name: string;
  column_mapping: Record<string, string>;
  created_at: string;
};

export type CreateImportTemplateInput = {
  name: string;
  column_mapping: Record<string, string>;
};

export async function listImportTemplates() {
  const { data } = await apiClient.get<ImportTemplate[]>("/import-templates");
  return data;
}

export async function createImportTemplate(input: CreateImportTemplateInput) {
  const { data } = await apiClient.post<ImportTemplate>("/import-templates", input);
  return data;
}
