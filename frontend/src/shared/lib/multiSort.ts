import type { SortConfig } from "@/shared/hooks/useTableQueryEngine";

/**
 * Click cycle for multi-sort: none -> asc (append with next priority) -> desc -> removed.
 */
export function nextMultiSortConfigs<Field extends string>(
  prev: SortConfig<Field>[],
  field: Field,
): SortConfig<Field>[] {
  const existing = prev.findIndex((s) => s.field === field);
  if (existing === -1) {
    return [...prev, { field, order: "asc" }];
  }

  const next = [...prev];
  if (next[existing].order === "asc") {
    next[existing] = { field, order: "desc" };
  } else {
    next.splice(existing, 1);
  }
  return next;
}

