import type { SortConfig } from "@/shared/hooks/useTableQueryEngine";

/**
 * Click cycle for multi-sort: none -> desc (append with next priority) -> asc -> removed.
 */
export function nextMultiSortConfigs<Field extends string>(
  prev: SortConfig<Field>[],
  field: Field,
): SortConfig<Field>[] {
  const existing = prev.findIndex((s) => s.field === field);
  if (existing === -1) {
    return [...prev, { field, order: "desc" }];
  }

  const next = [...prev];
  if (next[existing].order === "desc") {
    next[existing] = { field, order: "asc" };
  } else {
    next.splice(existing, 1);
  }
  return next;
}

