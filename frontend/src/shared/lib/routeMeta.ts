/**
 * Происхождение маршрута позиции плана (CONTEXT.md): как маршрут появился —
 * собран по профилю правил (`dynamic_build`), подобран автоматчиком (`auto`),
 * назначен оператором (`manual`), унаследован (`legacy`) или не найден
 * (`missing`).
 *
 * Единственная реализация подписи: страница плана и «Контроль выполнения»
 * рисуют один и тот же результат.
 */

export type RouteMetaLike = {
  route_source: string | null;
  route_origin: string | null;
  route_match_quality: string | null;
  route_assigned_at: string | null;
};

export type RouteOrigin =
  /** Маршрут есть, но подпись не нужна — UI рисует галочку «маршрут найден». */
  | { kind: "checkmark" }
  /** Осмысленная текстовая подпись происхождения. */
  | { kind: "text"; text: string }
  /** Данных нет или значение неизвестно — подписи нет, UI рисует `—`. */
  | { kind: "none" };

export function formatRouteAssignedAt(value: string | null | undefined): string {
  if (!value) return "дата неизвестна";
  const dt = new Date(value);
  if (Number.isNaN(dt.getTime())) return "дата неизвестна";
  return dt.toLocaleString("ru-RU", {
    day: "2-digit",
    month: "2-digit",
    year: "numeric",
    hour: "2-digit",
    minute: "2-digit",
  });
}

export function routeOrigin(route: RouteMetaLike): RouteOrigin {
  // `dynamic_build` приходит с origin=auto — проверяем раньше ветки автомаппинга,
  // иначе собранный по профилю маршрут подписывался бы как «автомаппинг».
  if (route.route_source === "dynamic_build") {
    return { kind: "checkmark" };
  }
  if (route.route_origin === "manual_confirmed" || route.route_source === "manual") {
    return { kind: "text", text: `вручную • ${formatRouteAssignedAt(route.route_assigned_at)}` };
  }
  if (route.route_origin === "auto" || route.route_source === "auto") {
    const quality = route.route_match_quality === "exact" ? "полное" : "скорректирован";
    return {
      kind: "text",
      text: `автомаппинг (${quality}) • ${formatRouteAssignedAt(route.route_assigned_at)}`,
    };
  }
  if (route.route_origin === "legacy" || route.route_source === "legacy") {
    return { kind: "text", text: "legacy • дата неизвестна" };
  }
  if (route.route_source === "missing") {
    return { kind: "text", text: "не найден" };
  }
  return { kind: "none" };
}

/** Текстовая подпись происхождения; `null` — подписи нет (маршрут с галочкой). */
export function routeOriginLabel(origin: RouteOrigin): string | null {
  if (origin.kind === "text") return origin.text;
  if (origin.kind === "none") return "—";
  return null;
}
