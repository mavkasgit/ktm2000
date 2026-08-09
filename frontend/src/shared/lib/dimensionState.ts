/**
 * Общий модуль размерности артикула (#79, ADR-0012).
 * Размерность — ровно одна ось описания продукта: `length` (1D, «Длина, мм»),
 * `area` (2D), `volume` (3D). Три экрана (форма артикула, список сырья,
 * секция 2D/3D-полей) используют эти предикаты/константы вместо литералов.
 */
import type { DimensionState } from "@/shared/api/products";

/** Подписи состояний размерности для UI (табы, бейджи). */
export const DIMENSION_STATE_LABELS: Record<DimensionState, string> = {
  length: "Длина",
  area: "2D",
  volume: "3D",
};

/** Все состояния размерности в доменном порядке. */
export const DIMENSION_STATES: DimensionState[] = ["length", "area", "volume"];

/** Предикат «это длина» — единственная размерность, участвующая в подвесе (#59). */
export function isLengthState(state: DimensionState | null | undefined): boolean {
  return (state ?? "length") === "length";
}

/**
 * Поля 2D/3D размерностей: code → подпись. Для `length` — null:
 * 1D не имеет набора полей (длины ведутся через product_lengths).
 */
export const DIMENSION_FIELDS: Record<
  Exclude<DimensionState, "length">,
  { code: string; label: string }[]
> = {
  area: [
    { code: "length_mm", label: "Длина, мм" },
    { code: "width_mm", label: "Ширина, мм" },
    { code: "thickness_mm", label: "Толщина, мм" },
  ],
  volume: [
    { code: "length_mm", label: "Длина, мм" },
    { code: "width_mm", label: "Ширина, мм" },
    { code: "height_mm", label: "Высота, мм" },
  ],
};

/** Коды полей размерности, или null для `length`. */
export function dimensionFieldCodes(
  state: DimensionState,
): string[] | null {
  if (isLengthState(state)) return null;
  return DIMENSION_FIELDS[state as Exclude<DimensionState, "length">].map((f) => f.code);
}
