/**
 * Grid template columns for the plan positions table.
 * 11 columns: Id, Строка, Артикул, Кол-во, Размер, Наименование, Маршрут,
 * Ошибки, Предупр., Действия, Сброс
 *
 * auto — sizes to content (Id, Строка, Артикул, Кол-во, Размер, Ошибки, Предупр., Действия)
 * minmax(200px, 1fr) — Наименование: min 200px, shares leftover space
 * minmax(250px, 2fr) — Маршрут: min 250px, takes 2x share of leftover vs Наименование
 */
export const PLAN_POSITIONS_GRID =
  'auto auto auto auto auto minmax(200px, 1fr) minmax(250px, 2fr) auto auto auto 2.5rem';

