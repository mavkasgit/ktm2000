/**
 * components/PlanHangerDisplay.tsx
 * ================================
 * Правила подсчёта подвесов и нормы на подвес для листа плана участка.
 *
 * Ячейки колонок печати собираются из описаний колонок в
 * `planPrintSettings.ts`, поэтому здесь только вычисления.
 */

import type { SectionBoardTask } from "@/shared/api/shopfloor";
import { fmtQtyPrecise } from "@/shared/lib/quantityFormat";

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

type PairSnapshot = {
  resolved?: boolean;
  quantity_per_hanger?: string | number | null;
};

/** Снапшот пары из payload задачи (``product_pair``). */
function getPairSnapshot(payload: Record<string, unknown>): PairSnapshot | null {
  const pair = payload.product_pair;
  return pair && typeof pair === "object" ? (pair as PairSnapshot) : null;
}

/** N пары из снапшота (resolved + положительная N); null — снапшота/нормы нет. */
function getSnapshotPairQuantity(payload: Record<string, unknown>): number | null {
  const pair = getPairSnapshot(payload);
  if (pair?.resolved !== true) return null;
  const value = Number(pair.quantity_per_hanger);
  return Number.isFinite(value) && value > 0 ? value : null;
}

/** Извлекает количество на подвес из source_payload задачи.
 * Приоритет как у бэкенда: ручной override позиции (> 0) → снапшот
 * ``product_pair`` (> 0); неположительный override не считается override.
 * Для обычных профилей источник — ``quantity_per_hanger``.
 */
export function getQtyPerHanger(task: SectionBoardTask): number | null {
  const payload = task.source_payload as Record<string, unknown> | null;
  if (!payload) return null;

  const override = payload.quantity_per_hanger;
  if (typeof override === "number" && override > 0) return override;

  return getSnapshotPairQuantity(payload);
}

/** Для парных профилей возвращает одно N, для обычных — null */
export function getPairedHangerLabel(task: SectionBoardTask): string | null {
  const payload = task.source_payload as Record<string, unknown> | null;
  if (!payload) return null;

  if (getPairSnapshot(payload)?.resolved !== true) return null;
  const quantity = getQtyPerHanger(task);
  return quantity !== null ? fmtQtyPrecise(quantity) : null;
}

/** Считает количество подвесов по логике backend (hanger_quantity.py) */
export function adjustQtyToHanger(qty: number, qtyPerHanger: number | null) {
  if (!qtyPerHanger || qtyPerHanger <= 0 || qty <= 0) {
    return { hangers: 1 };
  }
  const hangers = Math.ceil(qty / qtyPerHanger);
  return { hangers };
}

