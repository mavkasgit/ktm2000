import { getErrorMessage } from "@/shared/api/client";
import {
  createTransfer,
  finalReleaseTask,
  type ReadyToTransferTask,
} from "@/shared/api/transfers";
import {
  summarizeBulkResults,
  type BulkActionResultItem,
  type BulkActionSummary,
  type BulkRunnerProgress,
} from "@/shared/bulk";
import { isFinalReadyRow } from "./groupReadyTransfers";

export function makeIdempotencyKey(prefix: string): string {
  if (typeof crypto !== "undefined" && "randomUUID" in crypto) {
    return `${prefix}-${crypto.randomUUID()}`;
  }
  return `${prefix}-${Date.now()}-${Math.floor(Math.random() * 1_000_000)}`;
}

/** Количества в домене — `Numeric(14,3)`; считаем в тысячных, чтобы не ловить дрейф float. */
const QTY_SCALE = 1000;

function toScaledQty(value: string | number | null | undefined): number {
  const parsed = typeof value === "number" ? value : parseFloat(value ?? "");
  return Number.isFinite(parsed) ? Math.round(parsed * QTY_SCALE) : 0;
}

export interface TransferQuantitiesPlan {
  /** Количество по каждой строке — тот же порядок и длина, что у `rows`. */
  quantities: string[];
  /** Сколько из общего количества не удалось распределить: столько материала ещё не готово. */
  undistributed: number;
}

/**
 * Распределение общего количества группы по строкам: последовательно, в порядке
 * строк с бэка, каждая берёт `min(остаток, transferable)`. Без общего количества
 * (`totalQuantity` не задан) каждая строка отправляется своим `transferable` —
 * так работает чекбокс-режим.
 */
export function planTransferQuantities(
  rows: ReadyToTransferTask[],
  totalQuantity?: number,
): TransferQuantitiesPlan {
  if (totalQuantity === undefined) {
    return { quantities: rows.map((row) => row.transferable_quantity), undistributed: 0 };
  }

  let remaining = toScaledQty(totalQuantity);
  const quantities = rows.map((row) => {
    const take = Math.min(remaining, toScaledQty(row.transferable_quantity));
    remaining -= take;
    return String(take / QTY_SCALE);
  });

  return { quantities, undistributed: remaining / QTY_SCALE };
}

export interface TransferBatchOptions {
  rows: ReadyToTransferTask[];
  /** Префикс ключа идемпотентности: отличает массовую передачу от групповой. */
  idempotencyPrefix: string;
  /**
   * Общее количество на всю пачку (групповая передача): распределяется по строкам,
   * см. `planTransferQuantities`. Без него каждая строка уходит своим количеством.
   */
  totalQuantity?: number;
  comment?: string;
  /** Только для чекбокс-режима: учёт исполнителя и времени операции. */
  executorUserId?: number;
  performedAt?: string;
  physicalHandoverAt?: string;
  postFactum?: boolean;
  onProgress?: (progress: BulkRunnerProgress) => void;
}

export interface TransferBatchOutcome {
  results: BulkActionResultItem<number>[];
  summary: BulkActionSummary;
  /** Не распределилось (введено больше, чем доступно): материал ещё не готов. */
  undistributed: number;
}

/**
 * Единственная реализация пакетной отправки готовых к передаче строк: по одной
 * строке — либо передача на следующий этап (`createTransfer`), либо финальный
 * выпуск (`finalReleaseTask`). Габарит берётся из строки как есть.
 *
 * Каждый запрос независим: ошибка одной строки не отменяет остальные, поэтому
 * провал возвращается как `failed` в `results`, а не исключением. Строка, которой
 * не досталось запрошенного количества, не отправляется вовсе (`skipped`).
 */
export async function runTransferBatch({
  rows,
  idempotencyPrefix,
  totalQuantity,
  comment,
  executorUserId,
  performedAt,
  physicalHandoverAt,
  postFactum,
  onProgress,
}: TransferBatchOptions): Promise<TransferBatchOutcome> {
  const { quantities, undistributed } = planTransferQuantities(rows, totalQuantity);
  const results: BulkActionResultItem<number>[] = [];
  let completed = 0;

  onProgress?.({ total: rows.length, completed, running: rows.length > 0 });

  for (const [index, row] of rows.entries()) {
    const label = `Позиция #${row.plan_position_id} (${row.product_sku ?? "—"})`;
    const quantity = quantities[index];

    if (toScaledQty(quantity) <= 0) {
      results.push({
        id: row.task_id,
        status: "skipped",
        reason: "Нет количества к передаче — материал ещё не готов",
        label,
      });
    } else {
      try {
        if (isFinalReadyRow(row)) {
          await finalReleaseTask(row.task_id, {
            quantity,
            comment,
            idempotency_key: makeIdempotencyKey(`${idempotencyPrefix}-final-${row.task_id}`),
            dimensions: row.dimensions ?? undefined,
          });
        } else {
          await createTransfer({
            from_task_id: row.task_id,
            to_task_id: undefined,
            quantity,
            comment,
            idempotency_key: makeIdempotencyKey(`${idempotencyPrefix}-${row.task_id}`),
            executor_user_id: executorUserId,
            performed_at: performedAt,
            physical_handover_at: physicalHandoverAt,
            post_factum: postFactum,
            dimensions: row.dimensions ?? undefined,
          });
        }

        results.push({ id: row.task_id, status: "success", label });
      } catch (err) {
        results.push({ id: row.task_id, status: "failed", reason: getErrorMessage(err), label });
      }
    }

    completed++;
    onProgress?.({ total: rows.length, completed, running: completed < rows.length });
  }

  return { results, summary: summarizeBulkResults(results), undistributed };
}
