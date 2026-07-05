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