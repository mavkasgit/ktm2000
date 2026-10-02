/**
 * lib/factQuantity.ts — ввод факта в двух режимах (#283).
 *
 * Поле факта принимает две записи: **«+100»** — добавить 100 к записанному
 * факту, **«500»** — факт станет 500. Режим несёт ведущий «+» (правило набора —
 * `normalizeQuantityInput`, ADR-0032), а перевод «ввод → порция» живёт здесь.
 *
 * Почему порция, а не итог: бэкенд принимает **порцию** — `good_quantity`
 * кладёт проводку ровно на введённое число (`operations_tasks.py`,
 * `_post_good_portion`), и отрицательные количества отклоняет
 * (`Quantities must be >= 0`). Поэтому «факт станет 500» — это порция
 * `500 − записанное`, а не отдельный контракт.
 *
 * **Уменьшение факта отклоняется**: обратной проводки у массового завершения
 * нет, исправление записанного факта живёт в журнале «Отмена действий».
 * Причина — код общего словаря (ADR-0049), текст выбирает экран.
 */

import { parseQuantityInput, type QuantityInputMode } from "@/shared/lib/quantityInput";
import type { ActionReasonCode } from "@/shared/lib/actionReasons";

/** Причина, по которой ввод факта не применяется: факт меньше записанного. */
export const FACT_BELOW_RECORDED_REASON: ActionReasonCode = "fact_below_recorded";

export type FactQuantityResolution =
  /** Ввода нет — писать нечего. */
  | { kind: "none" }
  /**
   * Порция к записи. `target` — факт после записи: показывается оператору
   * («было 400 → станет 500»), чтобы «просто число» не читалось как добавка.
   */
  | { kind: "write"; mode: QuantityInputMode; quantity: number; target: number }
  /** Ввод не применить: причина — код словаря. */
  | { kind: "invalid"; reason: ActionReasonCode };

/**
 * Ввод → порция. `recorded` — записанный факт по этой колонке (годные или
 * брак), он же база для режима «факт станет N».
 */
export function resolveFactQuantity(input: string, recorded: number): FactQuantityResolution {
  const { mode, quantity } = parseQuantityInput(input);
  if (quantity === null) return { kind: "none" };
  if (mode === "add") return { kind: "write", mode, quantity, target: recorded + quantity };
  if (quantity < recorded) return { kind: "invalid", reason: FACT_BELOW_RECORDED_REASON };
  return { kind: "write", mode, quantity: quantity - recorded, target: quantity };
}

/**
 * Порция к записи по вводу: `0` — писать нечего (нет ввода или ввод отклонён).
 * Короткая форма для тех, кому не нужны режим и итог: суммы, потолки, дефицит.
 */
export function factPortion(input: string, recorded: number): number {
  const resolution = resolveFactQuantity(input, recorded);
  return resolution.kind === "write" ? resolution.quantity : 0;
}

/** Ввод применён (писать есть что). */
export function isFactInputApplicable(input: string, recorded: number): boolean {
  const resolution = resolveFactQuantity(input, recorded);
  return resolution.kind !== "invalid";
}
