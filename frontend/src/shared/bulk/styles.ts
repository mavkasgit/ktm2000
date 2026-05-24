/**
 * Shared bulk operation styles — green theme for selected items.
 */

export const BULK_STYLES = {
  // Row selection
  selectedRow: "bg-green-100 ring-1 ring-green-400",
  selectedMobileCard: "bg-green-100",

  // Group header selection
  selectedGroupHeader: "bg-green-200 hover:bg-green-300",
  selectedGroupContainer: "bg-green-200",

  // Selection label
  selectedLabel: "text-green-700",

  // Ring for visual focus
  selectedRing: "ring-1 ring-green-400",
} as const;
