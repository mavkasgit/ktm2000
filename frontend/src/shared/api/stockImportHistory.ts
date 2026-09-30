/**
 * Клиент истории импорта остатков (ADR-0052, ADR-0053).
 *
 * Отдельный файл от `stock.ts`: здесь не про остатки и проводки, а про
 * реестр батчей импорта — список, детали, скачивание исходника, откат и
 * мягкое удаление.
 *
 * Откат и удаление — только для администратора (ADR-0052 п.6): сервер
 * возвращает 403 остальным ролям, а `canRollback` в списке гасит кнопку заранее.
 */

import { apiClient } from "./client";

/** Статус батча: `applied` — залит, `rolled_back` — отменен. */
export type StockImportBatchStatus = "applied" | "rolled_back";


/** Причина, по которой батч нельзя откатить (для тултипа). */
export type StockImportRollbackBlocker =
  | "batch_not_last_for_location"
  | "batch_already_rolled_back"
  | "batch_location_unknown"
  | "batch_hidden";

export type StockImportBatch = {
  batch_id: number;
  /** Узел журнала действий, которым помечен батч; его и катит откат. */
  action_id: number;
  status: StockImportBatchStatus;
  /** Бэкфилл из `action_journal` (ADR-0052 п.7): файла и строк нет. */
  legacy: boolean;
  /** Перед заливкой баланс склада был погашен — откат вернёт и его. */
  clear_existing: boolean;
  filename: string | null;
  file_id: number | null;
  sheet_name: string | null;
  location_id: number | null;
  location_name: string | null;
  total_rows: number;
  imported_rows: number;
  skipped_rows: number;
  created_at: string;
  created_by_name: string | null;
  rolled_back_at: string | null;
  deleted_at: string | null;
  can_rollback: boolean;
  rollback_blocked_reason: StockImportRollbackBlocker | null;
};

export type StockImportRow = {
  row_id: number;
  source_row_number: number;
  /** Значение ячейки «Артикул» как в файле. */
  sku: string;
  /** Что реально сопоставлено; отличается при частичном совпадении. */
  matched_sku: string | null;
  product_id: number | null;
  product_sku: string | null;
  product_name: string | null;
  quantity: string | null;
  dimensions_label: string;
  target_section_id: number | null;
  target_section_name: string | null;
  quality_state: string | null;
  status: "valid" | "invalid";
  errors: string[];
  warnings: string[];
  raw_values: string[];
  /** Остаток на складе сейчас — ответ на вопрос после отката. */
  current_balance: string | null;
};

export type StockImportBatchDetail = {
  batch: StockImportBatch;
  rows: StockImportRow[];
};

export type RollbackStockImportResult = {
  rolled_back: boolean;
  batch_id: number;
  action_id: number;
  reversal_action_id: number;
  compensated_tx_ids: number[];
};

/** Человекочитаемая причина блокировки отката. */
export function importRollbackBlockerLabel(
  blocker: StockImportRollbackBlocker | null,
): string | null {
  switch (blocker) {
    case "batch_not_last_for_location":
      return "Откатить можно только последний импорт этого склада";
    case "batch_already_rolled_back":
      return "Батч уже отменен";
    case "batch_location_unknown":
      return "У импорта не сохранился склад — откат недоступен";
    case "batch_hidden":
      return "Батч скрыт из списка";
    default:
      return null;
  }
}

export async function getStockImportBatches(
  params: { locationId?: number; includeHidden?: boolean } = {},
): Promise<StockImportBatch[]> {
  const { data } = await apiClient.get<StockImportBatch[]>(
    "/stock/import/remainders/batches",
    { params },
  );
  return data;
}

export async function getStockImportBatch(
  batchId: number,
): Promise<StockImportBatchDetail> {
  const { data } = await apiClient.get<StockImportBatchDetail>(
    `/stock/import/remainders/batches/${batchId}`,
  );
  return data;
}

export async function rollbackStockImportBatch(
  batchId: number,
  planToken: string,
  reason?: string,
): Promise<RollbackStockImportResult> {
  const { data } = await apiClient.post<RollbackStockImportResult>(
    `/stock/import/remainders/batches/${batchId}/rollback`,
    { plan_token: planToken, reason },
  );
  return data;
}

export async function hideStockImportBatch(
  batchId: number,
  reason?: string,
): Promise<{ hidden: boolean; batch_id: number }> {
  const { data } = await apiClient.post<{ hidden: boolean; batch_id: number }>(
    `/stock/import/remainders/batches/${batchId}/hide`,
    { reason },
  );
  return data;
}

/**
 * Исходный файл батча. Legacy-батчи файла не имеют — кнопку гасит UI.
 *
 * Идёт через `apiClient`, а не ссылкой: авторизация живёт в заголовке
 * `Authorization`, а голая `<a href>` уводит браузер в навигацию без него,
 * и пользователь вместо файла получает JSON `401` на весь экран.
 */
export async function downloadStockImportBatchFile(
  batchId: number,
): Promise<Blob> {
  const { data } = await apiClient.get<Blob>(
    `/stock/import/remainders/batches/${batchId}/file`,
    { responseType: "blob" },
  );
  return data;
}
