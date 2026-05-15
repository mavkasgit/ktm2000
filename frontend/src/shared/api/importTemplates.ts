import { apiClient } from "./client";

export type ImportTemplate = {
  id: number;
  code: string | null;
  name: string;
  button_label: string | null;
  is_active: boolean;
  sort_order: number;
  column_mapping: Record<string, string>;
  description: string | null;
  created_at: string;
};

export type CreateImportTemplateInput = {
  name: string;
  code?: string | null;
  button_label?: string | null;
  is_active?: boolean;
  sort_order?: number;
  column_mapping?: Record<string, string>;
  description?: string | null;
};

export type UpdateImportTemplateInput = CreateImportTemplateInput;

export async function listImportTemplates() {
  const { data } = await apiClient.get<ImportTemplate[]>("/import-templates");
  return data;
}

export async function createImportTemplate(input: CreateImportTemplateInput) {
  const { data } = await apiClient.post<ImportTemplate>("/import-templates", input);
  return data;
}

export async function updateImportTemplate(templateId: number, input: UpdateImportTemplateInput) {
  const { data } = await apiClient.put<ImportTemplate>(`/import-templates/${templateId}`, input);
  return data;
}

export async function deleteImportTemplate(templateId: number) {
  await apiClient.delete(`/import-templates/${templateId}`);
}
