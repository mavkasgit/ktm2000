/**
 * Флаг рантайм-ширин предпросмотра (#483).
 *
 * По умолчанию выключен: без флага экран ведёт себя как раньше — текущие доли
 * из `remainderPreviewColumns`, без `pretext`, без пересчёта. Включается
 * переменной окружения сборки или query-параметром (удобно для проверки на
 * стенде без пересборки).
 */
export const OPTIMAL_COLUMN_WIDTHS_ENV = "VITE_SPG_OPTIMAL_COLUMN_WIDTHS";
export const OPTIMAL_COLUMN_WIDTHS_QUERY = "spgColumnWidths";
export const OPTIMAL_COLUMN_WIDTHS_QUERY_VALUE = "optimal";

export function isOptimalColumnWidthsEnabled(
  env: Record<string, unknown> = import.meta.env,
  search: string = typeof window === "undefined" ? "" : window.location.search,
): boolean {
  if (env[OPTIMAL_COLUMN_WIDTHS_ENV] === "1") return true;
  return (
    new URLSearchParams(search).get(OPTIMAL_COLUMN_WIDTHS_QUERY) ===
    OPTIMAL_COLUMN_WIDTHS_QUERY_VALUE
  );
}
