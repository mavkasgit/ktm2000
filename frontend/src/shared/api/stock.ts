import { apiClient } from "./client";

export type QualityState = "GOOD" | "SCRAP" | "REWORK" | "FINAL_SCRAP";

/** Бэкенд принимает lowercase: good | scrap | rework | final_scrap */
export function toApiQualityState(state: QualityState = "GOOD"): string {
  if (state === "FINAL_SCRAP") return "final_scrap";
  return state.toLowerCase();
}

export type StockBalanceEntry = {
  id: number;
  product_id: number;
  product_sku: string | null;
  location_id: number;
  location_name: string | null;
  quality_state: QualityState | "good" | "scrap" | "rework" | "final_scrap";
  balance_qty: string;
  completed_stages?: ImportOperationStep[];
  refreshed_at: string | null;
};

const QUALITY_STATE_LABELS: Record<string, string> = {
  GOOD: "Годный",
  good: "Годный",
  SCRAP: "Брак",
  scrap: "Брак",
  FINAL_SCRAP: "Окончательный брак",
  final_scrap: "Окончательный брак",
  REWORK: "Переделка",
  rework: "Переделка",
};

export function formatQualityStateLabel(state: string): string {
  return QUALITY_STATE_LABELS[state] ?? state;
}

export function formatBalanceQtyInteger(qty: string | number): string {
  const n = typeof qty === "string" ? Number.parseFloat(qty) : qty;
  if (!Number.isFinite(n)) return "—";
  return String(Math.round(n));
}

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

/** source_ref транзакций импорта остатков из Excel/буфера */
export const IMPORT_REMAINDERS_SOURCE_REF = "import_remainders_excel";

const STOCK_REASON_LABELS: Record<string, string> = {
  ISSUE_TO_WORK: "Выдача в работу",
  issue_to_work: "Выдача в работу",
  COMPLETE: "Завершено",
  complete: "Завершено",
  TRANSFER_SEND: "Передача отправлено",
  transfer_send: "Передача отправлено",
  TRANSFER_RECEIVE: "Передача получено",
  transfer_receive: "Передача получено",
  RETURN_TO_STOCK: "Возврат на склад",
  return_to_stock: "Возврат на склад",
  RETURN_TO_PREVIOUS: "Возврат на предыдущий участок",
  return_to_previous: "Возврат на предыдущий участок",
  FINAL_RELEASE: "Финальный выпуск",
  final_release: "Финальный выпуск",
  SCRAP: "Списание в брак",
  scrap: "Списание в брак",
  REWORK: "Переделка",
  rework: "Переделка",
  ADJUSTMENT_IN: "Корректировка +",
  adjustment_in: "Корректировка +",
  ADJUSTMENT_OUT: "Корректировка −",
  adjustment_out: "Корректировка −",
  MANUAL_IN: "Ручной приход",
  manual_in: "Ручной приход",
  MANUAL_OUT: "Ручной расход",
  manual_out: "Ручной расход",
};

/** Человекочитаемая причина движения; импорт остатков выделяется отдельно. */
export function formatStockReasonLabel(
  reason: string,
  sourceRef?: string | null,
): string {
  if (sourceRef === IMPORT_REMAINDERS_SOURCE_REF) {
    return "Импорт остатков";
  }
  return STOCK_REASON_LABELS[reason] ?? STOCK_REASON_LABELS[reason.toLowerCase()] ?? reason;
}

/** Бэкенд принимает lowercase enum values: manual_in, transfer_send, … */
export function toApiStockReason(reason: StockReason): string {
  return reason.toLowerCase();
}

export type StockTransactionEntry = {
  id: number;
  product_id: number;
  from_location_id: number | null;
  from_location_name: string | null;
  to_location_id: number | null;
  to_location_name: string | null;
  quantity: string;
  reason: StockReason | string;
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
  if (params?.quality_state) search.set("quality_state", toApiQualityState(params.quality_state));
  const qs = search.toString();
  const { data } = await apiClient.get<StockBalanceEntry[]>(
    `/v2/stock/balance${qs ? `?${qs}` : ""}`,
  );
  return data;
}

export async function getProductStockBalances(productId: number, qualityState?: QualityState): Promise<StockBalanceEntry[]> {
  const search = qualityState ? `?quality_state=${toApiQualityState(qualityState)}` : "";
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
  reason: StockReason | string;
  quantity: string;
  created_at: string | null;
};

export async function postStockAdjustment(payload: StockAdjustmentPayload): Promise<StockAdjustmentResponse> {
  const { data } = await apiClient.post<StockAdjustmentResponse>("/api/v2/stock/adjustment", {
    ...payload,
    quality_state: toApiQualityState(payload.quality_state),
  });
  return data;
}

export async function getStockTransactions(params?: StockTransactionsParams): Promise<StockTransactionEntry[]> {
  const search = new URLSearchParams();
  if (params?.product_id !== undefined) search.set("product_id", String(params.product_id));
  if (params?.transfer_id !== undefined) search.set("transfer_id", String(params.transfer_id));
  if (params?.task_id !== undefined) search.set("task_id", String(params.task_id));
  if (params?.reason) search.set("reason", toApiStockReason(params.reason));
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

// ─── Operations Reference (ImportOperationStep) ────────────────────────

export type ImportOperationStep = {
  sequence: number;
  section_code: string;
  section_name: string;
  section_icon?: string | null;
  section_icon_color?: string | null;
  operation_code: string | null;
  operation_name: string;
  op_icon?: string | null;
  op_icon_color?: string | null;
  is_significant: boolean;
};

export async function getRemainderImportOperations(): Promise<ImportOperationStep[]> {
  const { data } = await apiClient.get<ImportOperationStep[]>("/v2/stock/import/remainders/operations");
  return data;
}

// ─── Extended Remainder Types ──────────────────────────────────────────

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
  completed_operations_raw: string | null;
  completed_stages: ImportOperationStep[];
  target_section_name: string | null;
  target_section_id: number | null;
  quality_state_raw: string | null;
  quality_state: QualityState | "good" | "scrap" | "rework" | "final_scrap";
};

export const IMPORT_QUALITY_OPTIONS: { value: QualityState; label: string }[] = [
  { value: "GOOD", label: "Годный" },
  { value: "SCRAP", label: "Брак" },
  { value: "FINAL_SCRAP", label: "Окончательный брак" },
];

export function normalizeImportQualityState(
  state: string | null | undefined,
): QualityState {
  const norm = (state ?? "good").toLowerCase();
  if (norm === "final_scrap") return "FINAL_SCRAP";
  if (norm === "scrap") return "SCRAP";
  if (norm === "rework") return "REWORK";
  return "GOOD";
}

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
  location_id?: number;
  sheet_index?: number;
  row_selection?: string;
  quality_state?: QualityState;
  skip_invalid?: boolean;
  clear_existing?: boolean;
  target_section_overrides?: Record<number, number>; // row_number → section_id
  quality_state_overrides?: Record<number, QualityState>; // row_number → quality
};

export type RemainderImportSource =
  | { kind: "file"; file: File }
  | { kind: "clipboard"; clipboardText: string };

function appendRemainderImportSource(formData: FormData, source: RemainderImportSource) {
  if (source.kind === "file") {
    formData.append("file", source.file);
    return;
  }
  formData.append("clipboard_text", source.clipboardText);
}

export async function previewRemaindersExcel(
  source: RemainderImportSource,
  opts: RemainderImportOptions = {},
): Promise<RemainderPreviewResponse> {
  const formData = new FormData();
  appendRemainderImportSource(formData, source);
  if (opts.location_id != null) {
    formData.append("location_id", String(opts.location_id));
  }
  formData.append("quality_state", toApiQualityState(opts.quality_state));
  formData.append("sheet_index", String(opts.sheet_index ?? 0));
  if (opts.row_selection) formData.append("row_selection", opts.row_selection);
  if (opts.target_section_overrides && !opts.clear_existing) {
    formData.append("target_section_overrides", JSON.stringify(opts.target_section_overrides));
  }
  if (opts.quality_state_overrides && Object.keys(opts.quality_state_overrides).length > 0) {
    const payload = Object.fromEntries(
      Object.entries(opts.quality_state_overrides).map(([row, state]) => [
        row,
        toApiQualityState(state),
      ]),
    );
    formData.append("quality_state_overrides", JSON.stringify(payload));
  }
  const { data } = await apiClient.post<RemainderPreviewResponse>(
    "/v2/stock/import/remainders/preview",
    formData,
    { headers: { "Content-Type": "multipart/form-data" } },
  );
  return data;
}

export async function importRemaindersExcel(
  locationId: number,
  source: RemainderImportSource,
  opts: RemainderImportOptions = {},
): Promise<RemainderImportResponse> {
  const formData = new FormData();
  appendRemainderImportSource(formData, source);
  formData.append("location_id", String(locationId));
  formData.append("quality_state", toApiQualityState(opts.quality_state));
  formData.append("sheet_index", String(opts.sheet_index ?? 0));
  formData.append("skip_invalid", String(opts.skip_invalid ?? true));
  formData.append("clear_existing", String(opts.clear_existing ?? false));
  if (opts.row_selection) formData.append("row_selection", opts.row_selection);
  if (opts.target_section_overrides && !opts.clear_existing) {
    formData.append("target_section_overrides", JSON.stringify(opts.target_section_overrides));
  }
  if (opts.quality_state_overrides && Object.keys(opts.quality_state_overrides).length > 0) {
    const payload = Object.fromEntries(
      Object.entries(opts.quality_state_overrides).map(([row, state]) => [
        row,
        toApiQualityState(state),
      ]),
    );
    formData.append("quality_state_overrides", JSON.stringify(payload));
  }
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
