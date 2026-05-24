/**
 * Shared table row styles — consistent hover and selection across all tables.
 */

export const TABLE_ROW_STYLES = {
  // Default rows
  defaultRow: "hover:bg-accent/60 hover:outline hover:outline-1 hover:outline-ring/30",
  defaultGroupRow: "bg-blue-50/80 hover:bg-blue-100 hover:outline hover:outline-1 hover:outline-blue-300",
  defaultGroupHeader: "bg-blue-50/80 hover:bg-blue-100 hover:outline hover:outline-1 hover:outline-blue-300",
  defaultGroupContainer: "bg-muted/20",

  // Selected rows (bulk)
  selectedRow: "bg-green-100 ring-1 ring-green-400 hover:bg-green-200",
  selectedMobileCard: "bg-green-100",

  // Selected group header
  selectedGroupHeader: "bg-green-200 hover:bg-green-300",
  selectedGroupContainer: "bg-green-200",

  // Selection label
  selectedLabel: "text-green-700",

  // Ring for visual focus
  selectedRing: "ring-1 ring-green-400",
} as const;
