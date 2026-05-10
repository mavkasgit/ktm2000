import { apiClient } from "./client";

export type ImportBatchMode = "create_plan" | "append_to_plan" | "replace_draft_from_same_source";

export type ExcelImportResponse = {
  import_file_id: number;
  import_batch_id: number;
  production_plan_id: number;
  change_set_id: number;
  sheet_name: string;
  header_row_number: number;
  summary: Record<string, unknown>;
  items: Record<string, unknown>[];
};

export type ImportExcelInput = {
  file: File;
  sheet_index?: number;
  mode?: ImportBatchMode;
  production_plan_id?: number;
  plan_month?: string;
  plan_version?: string;
  template_id?: number;
  column_mapping?: Record<string, string>;
};

export type RecentImport = {
  id: number;
  production_plan_id: number;
  change_set_id: number | null;
  plan_name: string;
  plan_no: string;
  original_filename: string;
  mode: string;
  status: string;
  sheet_name: string;
  parsed_rows: number;
  total_rows: number;
  error_count: number;
  warning_count: number;
  summary: Record<string, unknown>;
  created_at: string;
};

export async function importExcel(input: ImportExcelInput) {
  const formData = new FormData();
  formData.append("file", input.file);

  const { data } = await apiClient.post<ExcelImportResponse>("/imports/excel", formData, {
      params: {
        sheet_index: input.sheet_index ?? 0,
        mode: input.mode ?? "create_plan",
        production_plan_id: input.production_plan_id,
        plan_month: input.plan_month,
        plan_version: input.plan_version,
        template_id: input.template_id,
        column_mapping: input.column_mapping,
      },
    headers: {
      "Content-Type": "multipart/form-data",
    },
  });

  return data;
}

export async function listRecentImports(limit: number = 10) {
  const { data } = await apiClient.get<RecentImport[]>("/imports/recent", {
    params: { limit },
  });
  return data;
}

export function getImportFileDownloadUrl(fileId: number) {
  return `/api/imports/files/${fileId}/download`;
}

export type ImportPosition = {
  id: number;
  source_row_number: number | null;
  source_sku: string;
  source_name: string | null;
  quantity: string;
  product_id: number | null;
  product_name: string | null;
  route_id: number | null;
  route_name: string | null;
  status: string;
  validation_status: string;
  validation_errors: string[];
  import_batch_id: number | null;
};

export async function getImportPositions(batchId: number) {
  const { data } = await apiClient.get<ImportPosition[]>(`/imports/${batchId}/positions`);
  return data;
}
