import { describe, expect, it } from "vitest";

import { formatRouteAssignedAt, routeOrigin, routeOriginLabel, type RouteMetaLike } from "./routeMeta";

function route(overrides: Partial<RouteMetaLike>): RouteMetaLike {
  return {
    route_source: null,
    route_origin: null,
    route_match_quality: null,
    route_assigned_at: null,
    ...overrides,
  };
}

describe("routeOrigin", () => {
  it("собранный по профилю маршрут — галочка, а не «автомаппинг»", () => {
    // `dynamic_build` приходит с origin=auto: ветка автомаппинга не должна его перехватывать.
    expect(
      routeOrigin(
        route({ route_source: "dynamic_build", route_origin: "auto", route_match_quality: "exact" }),
      ),
    ).toEqual({ kind: "checkmark" });
  });

  it("назначенный вручную — подпись с датой назначения", () => {
    expect(
      routeOrigin(
        route({
          route_source: "manual",
          route_origin: "manual_confirmed",
          route_assigned_at: "2026-02-01T10:00:00Z",
        }),
      ),
    ).toEqual({ kind: "text", text: expect.stringMatching(/^вручную • /) });
  });

  it("автомаппинг различает полное и скорректированное совпадение", () => {
    expect(routeOrigin(route({ route_source: "auto", route_match_quality: "exact" }))).toEqual({
      kind: "text",
      text: expect.stringMatching(/^автомаппинг \(полное\) • /),
    });
    expect(routeOrigin(route({ route_source: "auto", route_match_quality: "corrected" }))).toEqual({
      kind: "text",
      text: expect.stringMatching(/^автомаппинг \(скорректирован\) • /),
    });
  });

  it("унаследованный и ненайденный — осмысленные текстовые состояния", () => {
    expect(routeOrigin(route({ route_source: "legacy" }))).toEqual({
      kind: "text",
      text: "legacy • дата неизвестна",
    });
    expect(routeOrigin(route({ route_source: "missing" }))).toEqual({
      kind: "text",
      text: "не найден",
    });
  });

  it("нет данных или неизвестное значение — подписи нет", () => {
    expect(routeOrigin(route({}))).toEqual({ kind: "none" });
    expect(routeOrigin(route({ route_source: "something_new" }))).toEqual({ kind: "none" });
  });
});

describe("routeOriginLabel", () => {
  it("текст отдаётся как есть, отсутствие данных — прочерк, галочка — без подписи", () => {
    expect(routeOriginLabel({ kind: "text", text: "не найден" })).toBe("не найден");
    expect(routeOriginLabel({ kind: "none" })).toBe("—");
    expect(routeOriginLabel({ kind: "checkmark" })).toBeNull();
  });
});

describe("formatRouteAssignedAt", () => {
  it("пустая или битая дата — «дата неизвестна»", () => {
    expect(formatRouteAssignedAt(null)).toBe("дата неизвестна");
    expect(formatRouteAssignedAt("не дата")).toBe("дата неизвестна");
  });

  it("валидная ISO-дата превращается в подпись", () => {
    expect(formatRouteAssignedAt("2026-02-01T10:00:00Z")).not.toBe("дата неизвестна");
  });
});
