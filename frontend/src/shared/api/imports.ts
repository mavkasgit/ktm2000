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
  row_selection?: string;
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

export async function getExcelSheetNames(file: File): Promise<string[]> {
  const formData = new FormData();
  formData.append("file", file);
  const { data } = await apiClient.post<{ sheets: string[] }>("/imports/excel/sheets", formData, {
    headers: { "Content-Type": "multipart/form-data" },
  });
  return data.sheets;
}

export type SheetPreviewResponse = {
  sheet_name: string;
  header_row_number: number;
  total_rows: number;
  summary: Record<string, unknown>;
  items: Record<string, unknown>[];
};

export async function previewExcelSheet(
  file: File,
  options?: { sheet_index?: number; row_selection?: string },
): Promise<SheetPreviewResponse> {
  const formData = new FormData();
  formData.append("file", file);
  formData.append("sheet_index", String(options?.sheet_index ?? 0));
  if (options?.row_selection?.trim()) {
    formData.append("row_selection", options.row_selection.trim());
  }
  const { data } = await apiClient.post<SheetPreviewResponse>("/imports/excel/preview", formData, {
    headers: { "Content-Type": "multipart/form-data" },
  });
  return data;
}

export async function importExcel(input: ImportExcelInput) {
  const formData = new FormData();
  formData.append("file", input.file);
  formData.append("sheet_index", String(input.sheet_index ?? 0));
  formData.append("mode", input.mode ?? "create_plan");
  if (input.production_plan_id != null) {
    formData.append("production_plan_id", String(input.production_plan_id));
  }
  if (input.plan_month) {
    formData.append("plan_month", input.plan_month);
  }
  if (input.plan_version) {
    formData.append("plan_version", input.plan_version);
  }
  if (input.row_selection && input.row_selection.trim()) {
    formData.append("row_selection", input.row_selection.trim());
  }

  const { data } = await apiClient.post<ExcelImportResponse>("/imports/excel", formData, {
    params: {
      template_id: input.template_id,
      column_mapping: input.column_mapping ? JSON.stringify(input.column_mapping) : undefined,
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
