import { apiClient } from "./client";
import { qualityStateLabels, stockReasonLabels } from "@/shared/lib/generated-labels";

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
  /** Габаритная группа остатка (ADR-0001), например {"length_mm": 2700}; null — безразмерные/legacy. */
  dimensions?: Record<string, unknown> | null;
  /** Готовая подпись габарита с бэкенда («2,7 м» / «—»). */
  dimensions_label?: string;
  completed_stages?: ImportOperationStep[];
  refreshed_at: string | null;
};

export function formatQualityStateLabel(state: string): string {
  return qualityStateLabels[state] ?? state;
}

export function formatBalanceQtyInteger(qty: string | number): string {
  const n = typeof qty === "string" ? Number.parseFloat(qty) : qty;
  if (!Number.isFinite(n)) return "—";
  return String(Math.round(n));
}

/**
 * Подпись габарита (ADR-0001): {"length_mm": 2700} → «2,7 м»
 * (length_mm/1000, запятая как десятичный разделитель), null/пусто → «—».
 * Серверная подпись (dimensions_label) имеет приоритет, локальный расчёт —
 * fallback для мест, где ответ её не содержит.
 */
export function formatDimensionsLabel(
  dims?: Record<string, unknown> | null,
  serverLabel?: string | null,
): string {
  if (serverLabel) return serverLabel;
  if (!dims) return "—";
  const keys = Object.keys(dims);
  if (keys.length === 0) return "—";
  if (keys.length === 1 && keys[0] === "length_mm") {
    const mm = Number(dims.length_mm);
    if (Number.isFinite(mm) && mm > 0) {
      return `${String(mm / 1000).replace(".", ",")} м`;
    }
  }
  // Прочие наборы ключей — fallback «ключ: значение» в стабильном порядке.
  return keys
    .sort()
    .map((key) => `${key}: ${String(dims[key])}`)
    .join(", ");
}

/**
 * Подпись значения фильтра по размеру: JSON-строка канонического габарита
 * (`{"length_mm":2700}`) или `"null"` → человекочитаемая метка («2,7 м» / «—»).
 * Невалидная строка возвращается как есть.
 */
export function formatDimensionsFilterValue(value: string): string {
  if (value === "null") return "—";
  try {
    const parsed: unknown = JSON.parse(value);
    if (parsed && typeof parsed === "object" && !Array.isArray(parsed)) {
      return formatDimensionsLabel(parsed as Record<string, unknown>);
    }
  } catch {
    // невалидная строка — показываем как есть
  }
  return value;
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

/** Человекочитаемая причина движения; импорт остатков выделяется отдельно. */
export function formatStockReasonLabel(
  reason: string,
  sourceRef?: string | null,
): string {
  if (sourceRef === IMPORT_REMAINDERS_SOURCE_REF) {
    return "Импорт остатков";
  }
  return stockReasonLabels[reason] ?? stockReasonLabels[reason.toLowerCase()] ?? reason;
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
  /** Габарит движения (ADR-0001); null — безразмерные/legacy. */
  dimensions?: Record<string, unknown> | null;
  dimensions_label?: string;
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
  location_ids?: number[];
  quality_state?: QualityState;
  search?: string;
  sku?: string;
  quantity?: string;
  quality?: string;
  location?: string;
  operations?: string;
  sort_by?: string;
  sort_order?: "asc" | "desc";
  limit?: number;
  offset?: number;
};

export type StockBalancesListResponse = {
  balances: StockBalanceEntry[];
  total: number;
  limit: number;
  offset: number;
};

export type StockTransactionsParams = {
  product_id?: number;
  transfer_id?: number;
  task_id?: number;
  reason?: StockReason | string;
  location_id?: number;
  compensating?: boolean;
  search?: string;
  date_from?: string;
  date_to?: string;
  sort_by?: string;
  sort_order?: "asc" | "desc";
  from_location?: string;
  to_location?: string;
  quality_state?: string;
  comment?: string;
  limit?: number;
  offset?: number;
};

export type StockTransactionsListResponse = {
  transactions: StockTransactionEntry[];
  total: number;
  limit: number;
  offset: number;
};

export async function getStockBalances(
  params?: StockBalancesParams,
): Promise<StockBalancesListResponse> {
  const search = new URLSearchParams();
  if (params?.product_id !== undefined) search.set("product_id", String(params.product_id));
  if (params?.location_id !== undefined) search.set("location_id", String(params.location_id));
  if (params?.location_ids?.length) {
    for (const id of params.location_ids) {
      search.append("location_ids", String(id));
    }
  }
  if (params?.quality_state) search.set("quality_state", toApiQualityState(params.quality_state));
  if (params?.search) search.set("search", params.search);
  if (params?.sku) search.set("sku", params.sku);
  if (params?.quantity) search.set("quantity", params.quantity);
  if (params?.quality) search.set("quality", params.quality);
  if (params?.location) search.set("location", params.location);
  if (params?.operations) search.set("operations", params.operations);
  if (params?.sort_by) search.set("sort_by", params.sort_by);
  if (params?.sort_order) search.set("sort_order", params.sort_order);
  if (params?.limit !== undefined) search.set("limit", String(params.limit));
  if (params?.offset !== undefined) search.set("offset", String(params.offset));
  const qs = search.toString();
  const { data } = await apiClient.get<StockBalancesListResponse>(
    `/stock/balance${qs ? `?${qs}` : ""}`,
  );
  return data;
}

export async function getProductStockBalances(productId: number, qualityState?: QualityState): Promise<StockBalanceEntry[]> {
  const search = qualityState ? `?quality_state=${toApiQualityState(qualityState)}` : "";
  const { data } = await apiClient.get<StockBalanceEntry[]>(
    `/stock/balance/by-product/${productId}${search}`,
  );
  return data;
}

export type StockAdjustmentPayload = {
  product_id: number;
  location_id: number;
  quantity: number;
  reason: "manual_in" | "manual_out" | "adjustment_in" | "adjustment_out";
  quality_state?: QualityState;
  /** Габарит движения, например {"length_mm": 2700}; null/отсутствие — безразмерные штуки. */
  dimensions?: Record<string, unknown> | null;
  comment?: string;
};

export type StockAdjustmentResponse = {
  id: number;
  reason: StockReason | string;
  quantity: string;
  created_at: string | null;
};

export async function postStockAdjustment(payload: StockAdjustmentPayload): Promise<StockAdjustmentResponse> {
  const { data } = await apiClient.post<StockAdjustmentResponse>("/api/stock/adjustment", {
    ...payload,
    quality_state: toApiQualityState(payload.quality_state),
  });
  return data;
}

export async function getStockTransactions(
  params?: StockTransactionsParams,
): Promise<StockTransactionsListResponse> {
  const search = new URLSearchParams();
  if (params?.product_id !== undefined) search.set("product_id", String(params.product_id));
  if (params?.transfer_id !== undefined) search.set("transfer_id", String(params.transfer_id));
  if (params?.task_id !== undefined) search.set("task_id", String(params.task_id));
  if (params?.reason) {
    search.set(
      "reason",
      typeof params.reason === "string" ? params.reason : toApiStockReason(params.reason),
    );
  }
  if (params?.sort_by) search.set("sort_by", params.sort_by);
  if (params?.sort_order) search.set("sort_order", params.sort_order);
  if (params?.from_location) search.set("from_location", params.from_location);
  if (params?.to_location) search.set("to_location", params.to_location);
  if (params?.quality_state) search.set("quality_state", params.quality_state);
  if (params?.comment) search.set("comment", params.comment);
  if (params?.location_id !== undefined) search.set("location_id", String(params.location_id));
  if (params?.compensating !== undefined) search.set("compensating", String(params.compensating));
  if (params?.search) search.set("search", params.search);
  if (params?.date_from) search.set("date_from", params.date_from);
  if (params?.date_to) search.set("date_to", params.date_to);
  if (params?.limit !== undefined) search.set("limit", String(params.limit));
  if (params?.offset !== undefined) search.set("offset", String(params.offset));
  const qs = search.toString();
  const { data } = await apiClient.get<StockTransactionsListResponse>(
    `/stock/transactions${qs ? `?${qs}` : ""}`,
  );
  return data;
}

// ─── Remainder Excel Import (stock) ──────────────────────────────────────

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
  const { data } = await apiClient.get<ImportOperationStep[]>("/stock/import/remainders/operations");
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
  /** Сырое значение колонки «Длина» (метры, как в Excel). */
  length_raw: string | null;
  /** Габариты строки, например {"length_mm": 2700}; null = безразмерные. */
  dimensions: Record<string, number> | null;
  /** Подпись габарита для предпросмотра («2,7 м» / «—»). */
  dimensions_label: string;
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

export type RemainderSectionMeta = {
  source_row_number: number;
  status: "valid" | "invalid";
  target_section_id: number | null;
  target_section_name: string | null;
};

export type RemainderPreviewResponse = {
  sheet_name: string;
  total_rows: number;
  summary: RemainderImportSummary;
  section_meta: RemainderSectionMeta[];
  items: RemainderImportItem[];
  items_total: number;
  limit: number;
  offset: number;
};

export type RemainderImportResponse = {
  success: boolean;
  imported_count: number;
  errors: string[];
  transaction_ids: number[];
};

export type RemainderPreviewQueryParams = {
  search?: string;
  filter_status?: "all" | "invalid";
  sort_by?: "row" | "sku" | "quantity" | "length" | "operations" | "quality" | "section" | "errors";
  sort_order?: "asc" | "desc";
  limit?: number;
  offset?: number;
  row?: string;
  sku?: string;
  quantity?: string;
  length?: string;
  operations?: string;
  quality?: string;
  section?: string;
  errors?: string;
};

export type RemainderImportOptions = RemainderPreviewQueryParams & {
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
  formData.append("filter_status", opts.filter_status ?? "all");
  formData.append("sort_by", opts.sort_by ?? "row");
  formData.append("sort_order", opts.sort_order ?? "asc");
  formData.append("limit", String(opts.limit ?? 50));
  formData.append("offset", String(opts.offset ?? 0));
  if (opts.search) formData.append("search", opts.search);
  if (opts.row_selection) formData.append("row_selection", opts.row_selection);
  if (opts.row) formData.append("row", opts.row);
  if (opts.sku) formData.append("sku", opts.sku);
  if (opts.quantity) formData.append("quantity", opts.quantity);
  if (opts.length) formData.append("length", opts.length);
  if (opts.operations) formData.append("operations", opts.operations);
  if (opts.quality) formData.append("quality", opts.quality);
  if (opts.section) formData.append("section", opts.section);
  if (opts.errors) formData.append("errors", opts.errors);
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
    "/stock/import/remainders/preview",
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
    "/stock/import/remainders",
    formData,
    { headers: { "Content-Type": "multipart/form-data" } },
  );
  return data;
}

export async function downloadRemaindersImportTemplate(locationId: number): Promise<Blob> {
  const response = await apiClient.get<Blob>(
    `/stock/import/remainders/template?location_id=${locationId}`,
    { responseType: "blob" },
  );
  return response.data;
}
