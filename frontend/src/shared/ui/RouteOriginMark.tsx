import { Check } from "lucide-react";

/**
 * Отметка «маршрут найден» для маршрута, собранного по профилю правил
 * (`dynamic_build`, CONTEXT.md → «Происхождение маршрута»). Подпись вида
 * «динамический • дата» не несёт информации — достаточно галочки.
 */
export function RouteOriginMark() {
  return (
    <span
      className="inline-flex items-center align-text-bottom"
      title="маршрут найден"
      aria-label="маршрут найден"
    >
      <Check className="h-3.5 w-3.5 shrink-0 text-green-600" />
    </span>
  );
}
