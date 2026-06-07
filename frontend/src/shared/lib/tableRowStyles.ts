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
  selectedRow: "bg-indigo-50/80 ring-1 ring-indigo-300 hover:bg-indigo-100/70",
  selectedMobileCard: "bg-indigo-50/80 border border-indigo-200",

  // Selected group header
  selectedGroupHeader: "bg-indigo-100/70 hover:bg-indigo-200/60",
  selectedGroupContainer: "bg-indigo-50/40",

  // Selection label
  selectedLabel: "text-indigo-700 font-medium",

  // Ring for visual focus
  selectedRing: "ring-1 ring-indigo-300",
} as const;
