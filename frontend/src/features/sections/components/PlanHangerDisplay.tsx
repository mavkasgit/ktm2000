/**
 * components/PlanHangerDisplay.tsx
 * ================================
 * Компонент отображения количества подвесов для печатной формы плана.
 *
 * Используется только в специфических сценариях печати,
 * где нужно показать количество подвесов и штук на подвес.
 */

import type { SectionBoardTask } from "@/shared/api/shopfloor";

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

/** N пары: ручной override позиции приоритетнее снапшота; null — N нет. */
function getPairQuantity(payload: Record<string, unknown>): number | null {
  const pair = getPairSnapshot(payload);
  if (pair?.resolved !== true) return null;
  const override = payload.quantity_per_hanger;
  const raw = typeof override === "number" ? override : pair.quantity_per_hanger;
  const value = Number(raw);
  return Number.isFinite(value) && value > 0 ? value : null;
}

/** Извлекает количество на подвес из source_payload задачи.
 * Для парных профилей — N пары (override → снапшот ``product_pair``).
 * Для обычных — ``quantity_per_hanger``.
 */
export function getQtyPerHanger(task: SectionBoardTask): number | null {
  const payload = task.source_payload as Record<string, unknown> | null;
  if (!payload) return null;

  const pairQuantity = getPairQuantity(payload);
  if (pairQuantity !== null) return pairQuantity;

  // Standard profile
  const val = payload.quantity_per_hanger;
  return typeof val === "number" ? val : null;
}

/** Для парных профилей возвращает одно N, для обычных — null */
export function getPairedHangerLabel(task: SectionBoardTask): string | null {
  const payload = task.source_payload as Record<string, unknown> | null;
  if (!payload) return null;

  if (getPairSnapshot(payload)?.resolved !== true) return null;
  const quantity = getPairQuantity(payload);
  return quantity !== null ? String(Math.round(quantity)) : null;
}

/** Считает количество подвесов по логике backend (hanger_quantity.py) */
export function adjustQtyToHanger(qty: number, qtyPerHanger: number | null) {
  if (!qtyPerHanger || qtyPerHanger <= 0 || qty <= 0) {
    return { hangers: 1 };
  }
  const hangers = Math.ceil(qty / qtyPerHanger);
  return { hangers };
}

// ---------------------------------------------------------------------------
// PlanHangerColumns — колонки подвесов для таблицы
// ---------------------------------------------------------------------------

interface PlanHangerColumnsProps {
  groupQty: number;
  task: SectionBoardTask;
}

/** Рендерит две ячейки таблицы: "Подвесов" и "Кол-во на подвес" */
export function PlanHangerColumns({ groupQty, task }: PlanHangerColumnsProps) {
  const qtyPerHanger = getQtyPerHanger(task);
  const pairedLabel = getPairedHangerLabel(task);
  const { hangers } = adjustQtyToHanger(groupQty, qtyPerHanger);

  return (
    <>
      <td className="px-1 py-0.5 text-left">{hangers}</td>
      <td className="px-1 py-0.5 text-left">{pairedLabel ?? (qtyPerHanger != null ? String(qtyPerHanger) : "—")}</td>
    </>
  );
}

/** Рендерит два заголовка для колонки подвесов */
export function PlanHangerHeaders() {
  return (
    <>
      <th className="text-left px-1 py-0.5 font-semibold whitespace-nowrap">Подвесов</th>
      <th className="text-left px-1 py-0.5 font-semibold" style={{ minWidth: "60px" }}>
        Кол-во<br />на подвес
      </th>
    </>
  );
}

/** Ренерит две пустые ячейки для строки "Итого" */
export function PlanHangerEmpty() {
  return (
    <>
      <td className="px-1 py-0.5 text-right"></td>
      <td className="px-1 py-0.5 text-right"></td>
    </>
  );
}
