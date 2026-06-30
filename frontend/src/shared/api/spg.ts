import { apiClient } from "./client";

export type SpgSectionOut = {
  section_id: number;
  section_code: string;
  section_name: string;
  sort_order: number;
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
  in_work: number;
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
  in_work_total: number;
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
  in_work: number;
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

// ─── Remainders (Inventory) ─────────────────────────────────────────────────

export type SpgRemainder = {
  id: number;
  product_id: number;
  product_sku: string;
  product_name: string;
  spg_id: number;
  spg_code: string;
  spg_name: string;
  section_id?: number | null;
  section_code?: string | null;
  section_name?: string | null;
  remainder_quantity: number;
  original_issued: number;
  completed_stages: Array<{
    section_id: number;
    operation_code?: string | null;
    operation_name: string;
    sequence: number;
  }>;
  source: string;
  created_at: string;
};

export type ManualRemainderCreateInput = {
  product_id: number;
  section_id?: number | null;
  spg_id?: number | null;
  quantity: number;
  completed_stages?: Array<{
    section_id: number;
    operation_code?: string | null;
    operation_name: string;
    sequence: number;
  }>;
};

export type ManualRemainderUpdateInput = {
  quantity?: number;
  section_id?: number | null;
  spg_id?: number | null;
  completed_stages?: Array<{
    section_id: number;
    operation_code?: string | null;
    operation_name: string;
    sequence: number;
  }>;
};

export async function listSpgRemainders(spgId: number): Promise<SpgRemainder[]> {
  const { data } = await apiClient.get<SpgRemainder[]>(`/spg/${spgId}/remainders`);
  return data;
}

export async function createManualRemainder(
  spgId: number,
  payload: ManualRemainderCreateInput,
): Promise<SpgRemainder> {
  const { data } = await apiClient.post<SpgRemainder>(
    `/spg/${spgId}/remainders`,
    payload,
  );
  return data;
}

export async function updateManualRemainder(
  spgId: number,
  remainderId: number,
  payload: ManualRemainderUpdateInput,
): Promise<SpgRemainder> {
  const { data } = await apiClient.patch<SpgRemainder>(
    `/spg/${spgId}/remainders/${remainderId}`,
    payload,
  );
  return data;
}

export async function deleteManualRemainder(
  spgId: number,
  remainderId: number,
): Promise<void> {
  await apiClient.delete(`/spg/${spgId}/remainders/${remainderId}`);
}

// ─── Manual Stock Operations ───────────────────────────────────────────────

export type ManualOperationType = "in" | "out";

export type ManualOperationInput = {
  product_id: number;
  section_id: number;
  operation_type: ManualOperationType;
  quantity: number;
  reason?: string | null;
  comment?: string | null;
  idempotency_key?: string | null;
};

export type ManualOperationResponse = {
  movement_id: number;
  remainder_id: number | null;
  operation_type: ManualOperationType;
  product_id: number;
  product_sku: string;
  section_id: number;
  section_code: string;
  quantity: number;
  new_remainder_quantity: number;
  idempotent_replay?: boolean;
};

export async function performManualStockOperation(
  spgId: number,
  payload: ManualOperationInput,
): Promise<ManualOperationResponse> {
  const { data } = await apiClient.post<ManualOperationResponse>(
    `/spg/${spgId}/manual-operation`,
    payload,
  );
  return data;
}

// ─── Remainder History ─────────────────────────────────────────────────────

export type RemainderHistoryRemainder = {
  id: number;
  product_id: number;
  product_sku: string;
  product_name: string;
  spg_id: number;
  spg_code: string;
  spg_name: string;
  section_id?: number | null;
  section_code?: string | null;
  section_name?: string | null;
  remainder_quantity: number;
  original_issued: number;
  source: string;
  completed_stages: Array<{
    section_id: number;
    operation_code?: string | null;
    operation_name: string;
    sequence: number;
  }>;
  created_at: string;
  consumed_at: string | null;
  created_by?: number | null;
  created_by_user_name?: string | null;
};

export type RemainderHistoryOrigin = {
  task_id: number;
  task_status: string;
  planned_quantity: number;
  issued_quantity: number;
  completed_quantity: number;
  in_work_quantity: number;
  transferred_quantity: number;
  section_id: number;
  operation_code: string | null;
  operation_name: string | null;
  sequence: number | null;
  created_at: string;
};

export type RemainderHistoryRouteStep = {
  sequence: number;
  section_id: number;
  section_code: string;
  section_name: string;
  operation_code: string | null;
  operation_name: string;
  is_significant: boolean;
  is_final: boolean;
};

export type RemainderHistoryRoute = {
  route_id: number;
  route_name: string;
  route_code: string | null;
  current_sequence: number;
  steps: RemainderHistoryRouteStep[];
};

export type RemainderHistoryConsumedBy = {
  task_id: number;
  task_status: string;
  section_id: number;
  operation_code: string | null;
  operation_name: string | null;
  sequence: number | null;
};

export type RemainderHistoryMovement = {
  id: number;
  movement_type: string;
  quantity: number;
  task_id: number | null;
  from_section_id: number | null;
  to_section_id: number | null;
  reason: string | null;
  comment: string | null;
  created_at: string;
  performed_at: string | null;
  created_by?: number | null;
  created_by_user_name?: string | null;
  executor_user_id?: number | null;
  executor_user_name?: string | null;
};

export type RemainderHistoryResponse = {
  remainder: RemainderHistoryRemainder;
  origin: RemainderHistoryOrigin | null;
  route: RemainderHistoryRoute | null;
  consumed_by: RemainderHistoryConsumedBy | null;
  completed_stages: Array<{
    section_id: number;
    operation_code?: string | null;
    operation_name: string;
    sequence: number;
  }>;
  movements: RemainderHistoryMovement[];
};

export async function getRemainderHistory(
  spgId: number,
  remainderId: number,
): Promise<RemainderHistoryResponse> {
  const { data } = await apiClient.get<RemainderHistoryResponse>(
    `/spg/${spgId}/remainders/${remainderId}/history`,
  );
  return data;
}

// ─── SPG Availability (requires_lot gate) ───────────────────────────────────

export interface SpgAvailability {
  spg_id: number;
  product_id: number;
  section_id: number;
  available: number;
  requires_lot: boolean;
}

export async function getSpgAvailability(
  spgId: number,
  productId: number,
  sectionId: number,
): Promise<SpgAvailability> {
  const { data } = await apiClient.get<SpgAvailability>(
    `/spg/${spgId}/availability`,
    { params: { product_id: productId, section_id: sectionId } },
  );
  return data;
}

export type ImportRemaindersResponse = {
  success: boolean;
  imported_count: number;
  errors: string[];
};

export type SheetPreviewItem = {
  source_row_number: number;
  sku: string;
  quantity: number | null;
  completed_stages: Array<{
    section_id: number;
    section_code: string;
    section_name: string;
    operation_code: string | null;
    operation_name: string;
    sequence: number;
    is_significant: boolean;
  }>;
  status: "pending" | "invalid";
  errors: string[];
  warnings: string[];
  raw_values: string[];
  product_id: number | null;
  product_name: string | null;
  target_spg_id?: number;
  target_spg_name?: string;
  target_spg_code?: string;
};

export type SpgSheetPreviewResponse = {
  sheet_name: string;
  total_rows: number;
  summary: {
    total: number;
    valid: number;
    invalid: number;
    quantity_total: number;
  };
  items: SheetPreviewItem[];
};

export async function previewSpgRemaindersExcel(
  spgId: number,
  file: File,
  options?: {
    sheet_index?: number;
    row_selection?: string;
  }
): Promise<SpgSheetPreviewResponse> {
  const formData = new FormData();
  formData.append("file", file);
  formData.append("sheet_index", String(options?.sheet_index ?? 0));
  if (options?.row_selection?.trim()) {
    formData.append("row_selection", options.row_selection.trim());
  }
  const { data } = await apiClient.post<SpgSheetPreviewResponse>(
    `/spg/${spgId}/remainders/import/preview`,
    formData,
    {
      headers: {
        "Content-Type": "multipart/form-data",
      },
    }
  );
  return data;
}

export async function importRemaindersExcel(
  spgId: number,
  file: File,
  options?: {
    sheet_index?: number;
    row_selection?: string;
    skip_invalid?: boolean;
    clear_existing?: boolean;
  }
): Promise<ImportRemaindersResponse> {
  const formData = new FormData();
  formData.append("file", file);
  formData.append("sheet_index", String(options?.sheet_index ?? 0));
  if (options?.row_selection?.trim()) {
    formData.append("row_selection", options.row_selection.trim());
  }
  formData.append("skip_invalid", String(options?.skip_invalid ?? false));
  formData.append("clear_existing", String(options?.clear_existing ?? false));
  const { data } = await apiClient.post<ImportRemaindersResponse>(
    `/spg/${spgId}/remainders/import`,
    formData,
    {
      headers: {
        "Content-Type": "multipart/form-data",
      },
    }
  );
  return data;
}

export type SpgImportOperation = {
  operation_code: string | null;
  operation_name: string;
  section_name: string;
};

export async function getSpgImportOperations(spgId: number): Promise<SpgImportOperation[]> {
  const { data } = await apiClient.get<SpgImportOperation[]>(`/spg/${spgId}/remainders/import/operations`);
  return data;
}
