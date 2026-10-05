/** Shared visual tokens for data tables (plan, execution, etc.). */

export const DATA_TABLE_STYLES = {
  /** Scrollable table wrapper (execution and similar). */
  container: "min-w-0 overflow-x-hidden overflow-y-auto rounded-lg border",
  headerRow: "sticky top-0 z-20 border-b bg-muted text-xs font-medium text-muted-foreground shrink-0",
  headerCell: "p-2 text-left align-middle overflow-hidden",
  selectedRow: "bg-blue-100 ring-1 ring-blue-300",
} as const;

/**
 * Компактная строка (GLOSSARY.md, ADR-0030) — общий набор размеров строки
 * data-таблицы: высота, вертикальные отступы, размер действия и бейджа.
 *
 * Это единственное место, где набор задан. Таблица берёт его отсюда; свои
 * уточнения объявляет рядом с собой и разворачивает поверх
 * (`{ ...TABLE_ROW_COMPACT, ...tableOverrides }`) — базовый набор не
 * переопределяется изнутри, уточление всегда видно рядом с таблицей.
 *
 * `rowHeightPx` обязан совпадать с измеренной высотой строки:
 * max(высота действия, высота бейджа) + вертикальные отступы ячеек, без бордера.
 */
export const TABLE_ROW_COMPACT = {
  /** Оценка для VirtualizedTableBody (высота строки минус 1px бордер). */
  rowHeightPx: 40,
  /** Ячейка тела строки. */
  cell: "px-2 py-1",
  /** Ячейка шапки. */
  headerCell: "px-2 py-1.5",
  /** Кнопка действия в строке. */
  actionButton: "h-8 px-2 text-xs",
  /** Бейдж статуса в строке. */
  badge: "px-2 py-0",
} as const;

/**
 * Плотная строка 32px — уточнение к `TABLE_ROW_COMPACT` (ADR-0033).
 *
 * Общий набор остаётся 40px: его ещё берёт «Контроль выполнения», а решать
 * его плотность — отдельный разговор. Здесь же 32px объявлено один раз, чтобы
 * доска участков, «Передачи» и «Остатки»/ГХП не разъехались между собой:
 * раскладывается поверх базового (`{ ...TABLE_ROW_COMPACT, ...TABLE_ROW_DENSE }`).
 *
 * Высота складывается из h-6 (24px) и `py-1` (4+4). Текст причины
 * недоступности рядом с кнопкой — `text-[11px] leading-tight` — в 24px влезает
 * и переноса не даёт, поэтому строка не растёт (ADR-0030).
 */
export const TABLE_ROW_DENSE = {
  /** Оценка для VirtualizedTableBody (высота строки минус 1px бордер). */
  rowHeightPx: 32,
  /** Ячейка тела строки. */
  cell: "px-2 py-1",
  /** Ячейка шапки: та же ширина и вертикальный ритм, что у тела строки. */
  headerCell: "px-2 py-1",
  /** Кнопка действия в строке. */
  actionButton: "h-6 px-2 text-xs",
  /** Бейдж статуса в строке. */
  badge: "px-2 py-0 text-[11px]",
  /** Полоса «В ожидании» — живёт в той же таблице, высота обязана совпадать. */
  divider: "h-8",
} as const;