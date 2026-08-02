import { filterShortLabels } from "@/shared/lib/generated-labels";

export interface ActiveFilterSummary {
  count: number;
  labels: string[];
}

export interface BuildActiveFilterSummaryOptions {
  columnFilters?: Partial<Record<string, Set<string>>>;
  columnSearchQueries?: Partial<Record<string, string>>;
  columnLabels?: Record<string, string>;
}

export function buildActiveFilterSummary(
  filters: object,
  searchQuery: string,
  sortCount: number,
  options?: BuildActiveFilterSummaryOptions,
): ActiveFilterSummary {
  const labels: string[] = [];

  if (searchQuery.trim().length > 0) {
    labels.push("Поиск");
  }

  if (sortCount > 0) {
    labels.push(`Сортировка: ${sortCount}`);
  }

  for (const [key, value] of Object.entries(filters)) {
    if (typeof value === "string" && value !== "all") {
      const shortLabel = filterShortLabels[key] ?? key;
      labels.push(shortLabel);
    }
  }

  const columnLabels = options?.columnLabels ?? {};
  const columnFilters = options?.columnFilters ?? {};
  const columnSearchQueries = options?.columnSearchQueries ?? {};

  for (const [field, selected] of Object.entries(columnFilters)) {
    if (selected && selected.size > 0) {
      const label = columnLabels[field] ?? field;
      labels.push(`Колонка: ${label}`);
    }
  }

  for (const [field, query] of Object.entries(columnSearchQueries)) {
    if (query && query.trim()) {
      const label = columnLabels[field] ?? field;
      labels.push(`Поиск: ${label}`);
    }
  }

  return { count: labels.length, labels };
}