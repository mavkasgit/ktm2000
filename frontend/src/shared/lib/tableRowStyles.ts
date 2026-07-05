/**
 * Shared table row styles — consistent hover and selection across all tables.
 */

export const TABLE_ROW_STYLES = {
  // Default rows
  defaultRow: "hover:bg-accent/60 hover:outline hover:outline-1 hover:outline-ring/30",
  defaultGroupRow: "hover:bg-accent/40 hover:outline hover:outline-1 hover:outline-ring/20",
  defaultGroupHeader: "bg-slate-50/50 hover:bg-slate-100 hover:outline hover:outline-1 hover:outline-slate-200",
  defaultGroupContainer: "bg-slate-50/30",

  // Selected rows (bulk)
  selectedRow: "bg-blue-100 ring-1 ring-blue-300 hover:bg-blue-200/80",
  selectedMobileCard: "bg-blue-100 border border-blue-300",

  // Selected group header
  selectedGroupHeader: "bg-blue-100/90 hover:bg-blue-200/70",
  selectedGroupContainer: "bg-blue-50/50",

  // Selection label
  selectedLabel: "text-blue-700 font-medium",

  // Ring for visual focus
  selectedRing: "ring-1 ring-blue-300",
} as const;
