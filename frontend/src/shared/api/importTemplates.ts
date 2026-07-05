import { apiClient } from "./client";

export type ImportTemplate = {
  id: number;
  code: string | null;
  name: string;
  button_label: string | null;
  is_active: boolean;
  sort_order: number;
  column_mapping: Record<string, string | { header?: string; column?: string }>;
  description: string | null;
  profile_name?: string | null;
  created_at: string;
};

export type CreateImportTemplateInput = {
  name: string;
  code?: string | null;
  button_label?: string | null;
  is_active?: boolean;
  sort_order?: number;
  column_mapping?: Record<string, string | { header?: string; column?: string }>;
  description?: string | null;
};

export type UpdateImportTemplateInput = CreateImportTemplateInput;

export type ListImportTemplatesParams = {
  limit?: number;
  offset?: number;
};

export type ImportTemplatesListResponse = {
  items: ImportTemplate[];
  total: number;
  limit: number;
  offset: number;
};

export async function listImportTemplates(
  params: ListImportTemplatesParams = {},
): Promise<ImportTemplatesListResponse> {
  const { data } = await apiClient.get<ImportTemplatesListResponse>("/import-templates", { params });
  return data;
}

/** Все шаблоны для селектов/диалогов (пагинация, max 500 на запрос). */
export async function listAllImportTemplates(): Promise<ImportTemplate[]> {
  const pageSize = 500;
  const all: ImportTemplate[] = [];
  let offset = 0;
  let total = Infinity;

  while (offset < total) {
    const response = await listImportTemplates({ limit: pageSize, offset });
    all.push(...response.items);
    total = response.total;
    offset += response.items.length;
    if (response.items.length === 0) break;
  }

  return all;
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