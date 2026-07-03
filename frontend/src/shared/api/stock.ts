import { apiClient } from "./client";

export type QualityState = "GOOD" | "SCRAP" | "REWORK" | "QUARANTINE";

export type StockBalanceEntry = {
  id: number;
  product_id: number;
  location_id: number;
  location_name: string | null;
  quality_state: QualityState;
  balance_qty: string;
  refreshed_at: string | null;
};

export type StockReason =
  | "ISSUE_TO_WORK"
  | "COMPLETE"
  | "TRANSFER_SEND"
  | "TRANSFER_RECEIVE"
  | "RETURN_TO_STOCK"
  | "RETURN_TO_PREVIOUS"
  | "FINAL_RELEASE"
  | "SCRAP"
  | "REWORK"
  | "ADJUSTMENT_IN"
  | "ADJUSTMENT_OUT"
  | "MANUAL_IN"
  | "MANUAL_OUT";

export type StockTransactionEntry = {
  id: number;
  product_id: number;
  from_location_id: number | null;
  to_location_id: number | null;
  quantity: string;
  reason: StockReason;
  from_quality_state: QualityState;
  to_quality_state: QualityState;
  task_id: number | null;
  transfer_id: number | null;
  section_plan_line_id: number | null;
  compensates_tx_id: number | null;
  source_ref: string | null;
  idempotency_key: string | null;
  comment: string | null;
  created_by: number | null;
  executor_user_id: number | null;
  created_by_user_name: string | null;
  executor_user_name: string | null;
  performed_at: string | null;
  accounted_at: string | null;
  is_post_factum: boolean;
  created_at: string | null;
};

export type StockBalancesParams = {
  product_id?: number;
  location_id?: number;
  quality_state?: QualityState;
};

export type StockTransactionsParams = {
  product_id?: number;
  transfer_id?: number;
  task_id?: number;
  reason?: StockReason;
  location_id?: number;
  compensating?: boolean;
  limit?: number;
  offset?: number;
};

export async function getStockBalances(params?: StockBalancesParams): Promise<StockBalanceEntry[]> {
  const search = new URLSearchParams();
  if (params?.product_id !== undefined) search.set("product_id", String(params.product_id));
  if (params?.location_id !== undefined) search.set("location_id", String(params.location_id));
  if (params?.quality_state) search.set("quality_state", params.quality_state);
  const qs = search.toString();
  const { data } = await apiClient.get<StockBalanceEntry[]>(
    `/v2/stock/balance${qs ? `?${qs}` : ""}`,
  );
  return data;
}

export async function getProductStockBalances(productId: number, qualityState?: QualityState): Promise<StockBalanceEntry[]> {
  const search = qualityState ? `?quality_state=${qualityState}` : "";
  const { data } = await apiClient.get<StockBalanceEntry[]>(
    `/v2/stock/balance/by-product/${productId}${search}`,
  );
  return data;
}

export type StockAdjustmentPayload = {
  product_id: number;
  location_id: number;
  quantity: number;
  reason: "manual_in" | "manual_out" | "adjustment_in" | "adjustment_out";
  quality_state?: QualityState;
  comment?: string;
};

export type StockAdjustmentResponse = {
  id: number;
  reason: StockReason;
  quantity: string;
  created_at: string | null;
};

export async function postStockAdjustment(payload: StockAdjustmentPayload): Promise<StockAdjustmentResponse> {
  const { data } = await apiClient.post<StockAdjustmentResponse>("/api/v2/stock/adjustment", payload);
  return data;
}

export async function getStockTransactions(params?: StockTransactionsParams): Promise<StockTransactionEntry[]> {
  const search = new URLSearchParams();
  if (params?.product_id !== undefined) search.set("product_id", String(params.product_id));
  if (params?.transfer_id !== undefined) search.set("transfer_id", String(params.transfer_id));
  if (params?.task_id !== undefined) search.set("task_id", String(params.task_id));
  if (params?.reason) search.set("reason", params.reason);
  if (params?.location_id !== undefined) search.set("location_id", String(params.location_id));
  if (params?.compensating !== undefined) search.set("compensating", String(params.compensating));
  if (params?.limit !== undefined) search.set("limit", String(params.limit));
  if (params?.offset !== undefined) search.set("offset", String(params.offset));
  const qs = search.toString();
  const { data } = await apiClient.get<StockTransactionEntry[]>(
    `/v2/stock/transactions${qs ? `?${qs}` : ""}`,
  );
  return data;
}

// ─── Remainder Excel Import (v2/stock) ──────────────────────────────────────

export type RemainderImportItem = {
  source_row_number: number;
  sku: string;
  product_id: number | null;
  product_name: string | null;
  quantity: number | null;
  comment: string | null;
  status: "valid" | "invalid";
  errors: string[];
  raw_values: string[];
};

export type RemainderImportSummary = {
  total: number;
  valid: number;
  invalid: number;
  quantity_total: number;
};

export type RemainderPreviewResponse = {
  sheet_name: string;
  total_rows: number;
  summary: RemainderImportSummary;
  items: RemainderImportItem[];
};

export type RemainderImportResponse = {
  success: boolean;
  imported_count: number;
  errors: string[];
  transaction_ids: number[];
};

export type RemainderImportOptions = {
  sheet_index?: number;
  row_selection?: string;
  quality_state?: QualityState;
  skip_invalid?: boolean;
  clear_existing?: boolean;
};

export async function previewRemaindersExcel(
  locationId: number,
  file: File,
  opts: RemainderImportOptions = {},
): Promise<RemainderPreviewResponse> {
  const formData = new FormData();
  formData.append("file", file);
  formData.append("location_id", String(locationId));
  formData.append("quality_state", opts.quality_state ?? "GOOD");
  formData.append("sheet_index", String(opts.sheet_index ?? 0));
  if (opts.row_selection) formData.append("row_selection", opts.row_selection);
  const { data } = await apiClient.post<RemainderPreviewResponse>(
    "/v2/stock/import/remainders/preview",
    formData,
    { headers: { "Content-Type": "multipart/form-data" } },
  );
  return data;
}

export async function importRemaindersExcel(
  locationId: number,
  file: File,
  opts: RemainderImportOptions = {},
): Promise<RemainderImportResponse> {
  const formData = new FormData();
  formData.append("file", file);
  formData.append("location_id", String(locationId));
  formData.append("quality_state", opts.quality_state ?? "GOOD");
  formData.append("sheet_index", String(opts.sheet_index ?? 0));
  formData.append("skip_invalid", String(opts.skip_invalid ?? true));
  formData.append("clear_existing", String(opts.clear_existing ?? false));
  if (opts.row_selection) formData.append("row_selection", opts.row_selection);
  const { data } = await apiClient.post<RemainderImportResponse>(
    "/v2/stock/import/remainders",
    formData,
    { headers: { "Content-Type": "multipart/form-data" } },
  );
  return data;
}

export async function downloadRemaindersImportTemplate(locationId: number): Promise<Blob> {
  const response = await apiClient.get<Blob>(
    `/v2/stock/import/remainders/template?location_id=${locationId}`,
    { responseType: "blob" },
  );
  return response.data;
}
