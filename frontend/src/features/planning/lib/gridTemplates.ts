/**
 * Grid template columns for the plan positions table.
 * 11 columns: Id, Строка, Артикул, Кол-во, Размер, Наименование, Маршрут,
 * Ошибки, Предупр., Действия, Сброс
 *
 * Кол-во: minmax(150px, max-content) — вся строка «150 (3П) → 250 ГП» целиком.
 * Размер: minmax(200px, max-content) — «2,75 м → 0,9 м + 1,35 м …», переносится.
 * minmax(200px, 1fr) — Наименование: min 200px, shares leftover space
 * minmax(250px, 2fr) — Маршрут: min 250px, takes 2x share of leftover vs Наименование
 */
export const PLAN_POSITIONS_GRID =
  'auto auto auto minmax(150px, max-content) minmax(200px, max-content) minmax(200px, 1fr) minmax(250px, 2fr) auto auto auto 2.5rem';

