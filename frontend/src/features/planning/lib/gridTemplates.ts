/**
 * Grid template columns for the plan positions table.
 * 9 columns: Id, Строка, Артикул, Кол-во, Наименование, Маршрут, Ошибки, Предупр., Действия
 *
 * auto — sizes to content (Id, Строка, Артикул, Кол-во, Ошибки, Предупр., Действия)
 * minmax(200px, 1fr) — Наименование: min 200px, shares leftover space
 * minmax(250px, 2fr) — Маршрут: min 250px, takes 2x share of leftover vs Наименование
 */
export const PLAN_POSITIONS_GRID =
  'auto auto auto auto minmax(200px, 1fr) minmax(250px, 2fr) auto auto auto';

/**
 * Grid template for execution table — matches execution-table-columns order:
 * ID, №, План, Артикул, Кол-во, Наименование, Маршрут, Статус, Этап, Действия
 */
export const EXECUTION_GRID =
  'auto auto auto auto auto minmax(150px, 1fr) minmax(200px, 2fr) auto auto auto';

