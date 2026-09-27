/**
 * Формат вывода количества — единственный источник для всех экранов
 * (#201, ADR-0040). Домена два, и они не взаимозаменяемы:
 *
 * - `fmtQty` — **целые штуки**. Задания, доска, передачи, склад, брак, остатки.
 *   Дробь округляется: оператор считает трубы и заготовки, а не их доли.
 * - `fmtQtyPrecise` — **дробь живая**, до `QTY_PRECISION` знаков, хвостовые
 *   нули срезаются. Количество на подвес, состав ГП, превью плана: там
 *   «2,7 м» и «2,5 шт» — настоящие значения, и общий форматтер округлил бы
 *   2,5 до 3, то есть показал бы несуществующее количество.
 *
 * Общее у обоих:
 *
 * - **Разделитель тысяч запрещён.** E2E разбирает количество как `(\d+)\s*шт`
 *   ([`e2e/ui-helpers.ts`](../../e2e/ui-helpers.ts)), и `1 000` отдаёт туда
 *   `000`. Правило действует и на дробные домены.
 * - **Десятичный разделитель — запятая**, как у `formatDimensionsLabel`
 *   (ADR-0035): «2,7 м» и «2,5 шт» читаются одинаково.
 * - **Не-число → `QTY_EMPTY` («—»)**, а не «0» и не сырая строка. Ноль —
 *   это число; «—» означает, что значения нет. Разбирать значение в «0»
 *   стирало разницу между «ещё не введено» и «введено ноль».
 */

/** Знаков после десятичного разделителя в дробных доменах. */
export const QTY_PRECISION = 3;

/** Печать отсутствующего количества. */
export const QTY_EMPTY = "—";

/**
 * Значение количества → число или `null`, если числа за значением нет.
 * Строка с запятой числом не является: `Number("2,5")` — это `NaN`, и печатать
 * такое сырым текстом значит показать в таблице то, чего в данных нет.
 */
function toQuantityNumber(value: number | string | null | undefined): number | null {
  if (typeof value === "number") return Number.isFinite(value) ? value : null;
  if (typeof value !== "string") return null;
  const trimmed = value.trim();
  if (trimmed === "") return null;
  const parsed = Number(trimmed);
  return Number.isFinite(parsed) ? parsed : null;
}

/** Количество в целых штуках: `2.4` → «2», `undefined` → «—». */
export function fmtQty(value: number | string | null | undefined): string {
  const quantity = toQuantityNumber(value);
  if (quantity === null) return QTY_EMPTY;
  return String(Math.round(quantity));
}

/**
 * Количество с живой дробью: `2.5` → «2,5», `2.5004` → «2,5» (точность
 * `QTY_PRECISION`), `2` → «2». Хвостовые нули не печатаются: «2,000» и
 * «2» — одно и то же количество, а разные подписи читаются как разные числа.
 */
export function fmtQtyPrecise(value: number | string | null | undefined): string {
  const quantity = toQuantityNumber(value);
  if (quantity === null) return QTY_EMPTY;
  return String(Number(quantity.toFixed(QTY_PRECISION))).replace(".", ",");
}
