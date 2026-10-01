import { describe, expect, it } from "vitest";
import {
  buildColumnFilterPredicate,
  hasActiveColumnFilters,
  matchesPartialSearch,
  pickColumnApiValue,
  rankPartialSearchMatch,
  sortByPartialSearchMatch,
} from "./columnFilterSearch";

describe("columnFilterSearch", () => {
  it("matchesPartialSearch is case-insensitive and normalizes ё/е", () => {
    expect(matchesPartialSearch("ЮП-460", "юп")).toBe(true);
    expect(matchesPartialSearch("Ёжик", "еж")).toBe(true);
    expect(matchesPartialSearch("ABC-100", "юп")).toBe(false);
  });

  it("rankPartialSearchMatch prefers startsWith over contains", () => {
    expect(rankPartialSearchMatch("ЮП-460", "юп")).toBe(0);
    expect(rankPartialSearchMatch("Деталь ЮП-12", "юп")).toBeGreaterThan(0);
    expect(rankPartialSearchMatch("ABC", "юп")).toBe(Number.POSITIVE_INFINITY);
  });

  it("sortByPartialSearchMatch orders by relevance", () => {
    const sorted = sortByPartialSearchMatch(
      ["Деталь ЮП-12", "ЮП-460", "ABC-100"],
      "юп",
      (v) => v,
    );
    expect(sorted).toEqual(["ЮП-460", "Деталь ЮП-12"]);
  });

  it("buildColumnFilterPredicate uses partial search when query is set", () => {
    type Row = { sku: string };
    const predicate = buildColumnFilterPredicate<Row, "sku">({
      columnFilters: {},
      columnSearchQueries: { sku: "юп" },
      getCellValue: (row, field) => (field === "sku" ? row.sku : ""),
    });

    expect(predicate).not.toBeNull();
    expect(predicate!({ sku: "ЮП-460" })).toBe(true);
    expect(predicate!({ sku: "ABC-100" })).toBe(false);
  });

  it("buildColumnFilterPredicate falls back to Set when search is empty", () => {
    type Row = { sku: string };
    const predicate = buildColumnFilterPredicate<Row, "sku">({
      columnFilters: { sku: new Set(["ЮП-460"]) },
      columnSearchQueries: {},
      getCellValue: (row, field) => (field === "sku" ? row.sku : ""),
    });

    expect(predicate!({ sku: "ЮП-460" })).toBe(true);
    expect(predicate!({ sku: "ABC-100" })).toBe(false);
  });
});

/**
 * Граница мультивыбора и серверного фильтра (#242): мультивыбор разрешён
 * только у `clientOnly`-колонок (ADR-0044), сервер принимает одно значение.
 */
describe("мультивыбор и граница с сервером", () => {
  type Row = { sku: string };

  it("несколько выбранных значений в параметр запроса не превращаются", () => {
    // `size !== 1` → undefined: серверу одиночного значения не уходит ни один
    // из двух выборов, а не «первый попавшийся».
    expect(pickColumnApiValue({ sku: new Set(["ЮП-460", "ABC-100"]) }, {}, "sku")).toBeUndefined();
    // Пустой набор — это не выбор: параметра нет.
    expect(pickColumnApiValue({ sku: new Set<string>() }, {}, "sku")).toBeUndefined();
    expect(pickColumnApiValue({}, {}, "sku")).toBeUndefined();
    // Одиночный выбор уезжает как есть.
    expect(pickColumnApiValue({ sku: new Set(["ЮП-460"]) }, {}, "sku")).toBe("ЮП-460");
    // Поиск в приоритете над выбором: он всегда одно значение.
    expect(
      pickColumnApiValue({ sku: new Set(["ЮП-460"]) }, { sku: "юп" }, "sku"),
    ).toBe("юп");
  });

  it("мультивыбор сужает строки предикатом, хотя в запрос не уезжает", () => {
    const columnFilters = { sku: new Set(["ЮП-460", "ABC-100"]) };

    // Параметр серверу не передаётся…
    expect(pickColumnApiValue(columnFilters, {}, "sku")).toBeUndefined();
    // …но индикатор «фильтры активны» включён: сброс обязан убрать и этот выбор.
    expect(hasActiveColumnFilters(columnFilters, {})).toBe(true);
    // И предикат реально сужает — мультивыбор работает по уже загруженным строкам.
    const predicate = buildColumnFilterPredicate<Row, "sku">({
      columnFilters,
      columnSearchQueries: {},
      getCellValue: (row, field) => (field === "sku" ? row.sku : ""),
    });
    expect(predicate!({ sku: "ЮП-460" })).toBe(true);
    expect(predicate!({ sku: "ABC-100" })).toBe(true);
    expect(predicate!({ sku: "ЮП-200" })).toBe(false);
  });

  it("индикатор отражает состояние таблицы, а не отправленный параметр", () => {
    expect(hasActiveColumnFilters({}, {})).toBe(false);
    // Пустой набор — не выбор.
    expect(hasActiveColumnFilters({ sku: new Set<string>() }, {})).toBe(false);
    expect(hasActiveColumnFilters({ sku: new Set(["ЮП-460"]) }, {})).toBe(true);
    expect(hasActiveColumnFilters({}, { sku: "юп" })).toBe(true);
    // Пробелы в поиске не считаются вводом.
    expect(hasActiveColumnFilters({}, { sku: "   " })).toBe(false);
  });
});