/** Shared visual tokens for data tables (plan, execution, etc.). */

export const DATA_TABLE_STYLES = {
  /** Scrollable table wrapper (execution and similar). */
  container: "min-w-0 overflow-x-hidden overflow-y-auto rounded-lg border",
  /** Bordered frame with inner scroll body (plan grid layout). */
  frame: "min-w-0 rounded-lg border flex flex-col min-h-0 overflow-hidden",
  headerRow: "sticky top-0 z-20 border-b bg-muted text-xs font-medium text-muted-foreground shrink-0",
  headerCell: "p-2 text-left align-middle overflow-hidden",
  selectedRow: "bg-blue-100 ring-1 ring-blue-300",
} as const;

/**
 * Компактная строка (CONTEXT.md, ADR-0030) — общий набор размеров строки
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