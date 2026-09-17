/**
 * Количество подвесов для количества.
 *
 * Дробных подвесов не бывает: канон округляет количество позиции вверх до
 * кратного нормы (`hanger_rounding`, round_up_to_multiple), поэтому подвесы
 * считаются вверх. Нет нормы (или количество неположительное) — `null`.
 */
export function countHangers(
  quantity: number | string | null | undefined,
  quantityPerHanger: number | null | undefined,
): number | null {
  const qty = Number(quantity);
  const perHanger = Number(quantityPerHanger);
  if (!Number.isFinite(qty) || qty <= 0) return null;
  if (!Number.isFinite(perHanger) || perHanger <= 0) return null;
  return Math.ceil(qty / perHanger);
}
