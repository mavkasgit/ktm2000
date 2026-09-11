import { apiClient } from "./client";

export type ImportBatchMode = "create_plan" | "append_to_plan" | "replace_draft_from_same_source";

export type ExcelImportResponse = {
  import_file_id: number;
  import_batch_id: number;
  production_plan_id: number;
  change_set_id: number;
  template_id: number | null;
  rule_profile_id: number | null;
  rules_snapshot: Record<string, unknown>[];
  route_selection_diagnostics: Record<string, unknown>;
  sheet_name: string;
  header_row_number: number;
  summary: Record<string, unknown>;
  items: Record<string, unknown>[];
};

export type ImportCreateSummary = {
  total: number;
  valid: number;
  warning: number;
  invalid: number;
  duplicates: number;
  errors: Record<string, number>;
};

export type ImportLightItem = {
  item_id: number;
  source_row_numbers: number[];
  source_sku: string | null;
  source_name: string | null;
  quantity: string | number | null;
  status: string;
  change_action: string;
  codes: string[];
};

export type ImportFullItem = {
  id: number;
  source_row_number: number | null;
  source_ref: string | null;
  source_sku: string | null;
  change_action: string;
  status: string;
  warnings: string[];
  errors: string[];
  after_data: Record<string, unknown> | null;
  plan_position_id: number | null;
};

export type ImportBatchItemsResponse = {
  batch_id: number;
  change_set_id: number;
  items: ImportLightItem[];
  next_cursor: number | null;
  total: number;
};

export type ImportApplyStats = {
  total: number;
  valid: number;
  warning: number;
  invalid: number;
  duplicates: number;
  normal: number;
  uploadAll: number;
  uploadSkipInvalid: number;
  errors: Record<string, number>;
};

function toNumber(value: unknown): number {
  const n = Number(value ?? 0);
  return Number.isFinite(n) && n > 0 ? Math.trunc(n) : 0;
}

/** Диалог применения работает от серверного summary (§4.3), не от строк. */
export function buildImportApplyStats(summary: Record<string, unknown>): ImportApplyStats {
  const total = toNumber(summary.total);
  const warning = toNumber(summary.warning);
  const invalid = toNumber(summary.invalid);
  const duplicates = toNumber(summary.duplicates);
  const valid = toNumber(summary.valid ?? Math.max(total - warning - invalid, 0));
  const errors = (summary.errors as Record<string, number> | undefined) ?? {};
  return {
    total,
    valid,
    warning,
    invalid,
    duplicates,
    normal: Math.max(total - invalid - warning, 0),
    uploadAll: total,
    uploadSkipInvalid: Math.max(total - invalid, 0),
    errors,
  };
}

export async function fetchImportBatchItems(
  batchId: number,
  cursor = 0,
  limit = 200,
): Promise<ImportBatchItemsResponse> {
  const { data } = await apiClient.get<ImportBatchItemsResponse>(`/imports/batches/${batchId}/items`, {
    params: { cursor, limit },
  });
  return data;
}

/** Все лёгкие строки батча сразу (UI-пагинации нет): идёт курсором до конца. */
export async function fetchAllImportBatchItems(batchId: number): Promise<ImportLightItem[]> {
  const all: ImportLightItem[] = [];
  let cursor = 0;
  for (;;) {
    const page = await fetchImportBatchItems(batchId, cursor);
    all.push(...page.items);
    if (page.next_cursor == null) return all;
    cursor = page.next_cursor;
  }
}

export async function fetchImportItem(itemId: number, full = false): Promise<ImportLightItem | ImportFullItem> {
  const { data } = await apiClient.get<ImportLightItem | ImportFullItem>(`/imports/items/${itemId}`, {
    params: full ? { full: 1 } : {},
  });
  return data;
}

export type ImportExcelInput = {
  file: File;
  sheet_index?: number;
  mode?: ImportBatchMode;
  production_plan_id?: number;
  row_selection?: string;
  template_id?: number;
  column_mapping?: Record<string, string | { header: string; column: string }>;
  normalize_hanger_quantity?: boolean;
};

export type RecentImport = {
  id: number;
  production_plan_id: number;
  change_set_id: number | null;
  template_id: number | null;
  rule_profile_id: number | null;
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
  route_selection_diagnostics: Record<string, unknown>;
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
  options?: {
    sheet_index?: number;
    row_selection?: string;
    template_id?: number;
    mode?: ImportBatchMode;
    production_plan_id?: number;
    normalize_hanger_quantity?: boolean;
  },
): Promise<SheetPreviewResponse> {
  const formData = new FormData();
  formData.append("file", file);
  formData.append("sheet_index", String(options?.sheet_index ?? 0));
  formData.append("mode", options?.mode ?? "create_plan");
  if (options?.production_plan_id != null) {
    formData.append("production_plan_id", String(options.production_plan_id));
  }
  if (options?.row_selection?.trim()) {
    formData.append("row_selection", options.row_selection.trim());
  }
  formData.append("normalize_hanger_quantity", String(options?.normalize_hanger_quantity ?? true));
  const { data } = await apiClient.post<SheetPreviewResponse>("/imports/excel/preview", formData, {
    params: {
      template_id: options?.template_id,
    },
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
  if (input.row_selection && input.row_selection.trim()) {
    formData.append("row_selection", input.row_selection.trim());
  }
  formData.append("normalize_hanger_quantity", String(input.normalize_hanger_quantity ?? true));

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
  route_source: string | null;
  route_origin: string | null;
  route_match_quality: string | null;
  route_match_reason: string | null;
  route_assigned_at: string | null;
  route_manual_confirmed_at: string | null;
  status: string;
  validation_status: string;
  validation_errors: string[];
  import_batch_id: number | null;
};

export async function getImportPositions(batchId: number) {
  const { data } = await apiClient.get<ImportPosition[]>(`/imports/${batchId}/positions`);
  return data;
}
