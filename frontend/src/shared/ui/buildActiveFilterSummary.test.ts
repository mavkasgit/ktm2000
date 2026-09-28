import { describe, expect, it } from "vitest";

import { buildActiveFilterSummary } from "./buildActiveFilterSummary";

describe("buildActiveFilterSummary", () => {
  it("counts panel filters, search and sort", () => {
    const summary = buildActiveFilterSummary("abc", 2, {
      panelFilters: { status: "active", has_route: "all" },
    });

    expect(summary.count).toBe(3);
    expect(summary.labels).toEqual(["Поиск", "Сортировка: 2", "Статус"]);
  });

  it("экран без панели фильтров не объявляет пустую панель", () => {
    const summary = buildActiveFilterSummary("", 0, {
      columnFilters: { sku: new Set(["A-1"]) },
    });

    expect(summary.count).toBe(1);
    expect(summary.labels).toEqual(["Колонка: sku"]);
  });

  it("includes column filters and column search queries", () => {
    const summary = buildActiveFilterSummary("", 0, {
      columnFilters: { sku: new Set(["A-1"]) },
      columnSearchQueries: { name: "bolt" },
      columnLabels: { sku: "SKU", name: "Наименование" },
    });

    expect(summary.count).toBe(2);
    expect(summary.labels).toEqual(["Колонка: SKU", "Поиск: Наименование"]);
  });
});