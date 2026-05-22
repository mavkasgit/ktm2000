export interface ActiveFilterSummary {
  count: number;
  labels: string[];
}

const FILTER_SHORT_LABELS: Record<string, string> = {
  status: "Статус",
  validation_status: "Валидация",
  has_route: "Маршрут",
  has_errors: "Ошибки",
  has_warnings: "Предупр.",
  has_duplicates: "Дубликаты",
};

export function buildActiveFilterSummary(
  filters: object,
  searchQuery: string,
  sortCount: number,
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
      const shortLabel = FILTER_SHORT_LABELS[key] ?? key;
      labels.push(shortLabel);
    }
  }

  return { count: labels.length, labels };
}
