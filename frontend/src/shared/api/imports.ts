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
};

export async function importExcel(input: ImportExcelInput) {
  const formData = new FormData();
  formData.append("file", input.file);

  const { data } = await apiClient.post<ExcelImportResponse>("/imports/excel", formData, {
    params: {
      sheet_index: input.sheet_index ?? 0,
      mode: input.mode ?? "create_plan",
      production_plan_id: input.production_plan_id,
    },
    headers: {
      "Content-Type": "multipart/form-data",
    },
  });

  return data;
}
