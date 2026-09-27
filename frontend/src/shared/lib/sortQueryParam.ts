import type { SortConfig } from "@/shared/hooks/useTableQueryEngine";

/**
 * Сборка строки `?sort=field:order,field:order` из набора сортировок —
 * контракт общего хелпера бэкенда (`app/core/sorting.py`). Порядок в строке
 * это порядок приоритета: первое поле старше.
 *
 * Маппинг поля колонки в поле API задаёт вызывающий: у серверных таблиц он
 * не тождественный (колонка `План` уходит как `planned_qty`, `qty` и т. п.),
 * а колонки без сортировки на сервере в строке быть не должны.
 */
export function buildSortParam<Field extends string, ApiField extends string>(
  sortConfigs: SortConfig<Field>[],
  toApiField: (field: Field) => ApiField | undefined,
): string | undefined {
  const parts: string[] = [];
  for (const { field, order } of sortConfigs) {
    const apiField = toApiField(field);
    if (apiField === undefined) continue;
    parts.push(`${apiField}:${order}`);
  }
  return parts.length > 0 ? parts.join(",") : undefined;
}
