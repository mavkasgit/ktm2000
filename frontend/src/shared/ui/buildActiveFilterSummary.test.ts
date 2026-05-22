import { describe, it, expect } from "vitest";
import { buildActiveFilterSummary } from "./buildActiveFilterSummary";

describe("buildActiveFilterSummary", () => {
  it("returns count=0 and empty labels when nothing is active", () => {
    const summary = buildActiveFilterSummary(
      { status: "all", validation_status: "all" },
      "",
      0,
    );
    expect(summary.count).toBe(0);
    expect(summary.labels).toEqual([]);
  });

  it("counts search query as one active filter", () => {
    const summary = buildActiveFilterSummary(
      { status: "all" },
      "alpha",
      0,
    );
    expect(summary.count).toBe(1);
    expect(summary.labels).toContain("Поиск");
  });

  it("ignores whitespace-only search query", () => {
    const summary = buildActiveFilterSummary(
      { status: "all" },
      "   ",
      0,
    );
    expect(summary.count).toBe(0);
    expect(summary.labels).toEqual([]);
  });

  it("counts sort criteria with label", () => {
    const summary = buildActiveFilterSummary(
      { status: "all" },
      "",
      2,
    );
    expect(summary.count).toBe(1);
    expect(summary.labels).toContain("Сортировка: 2");
  });

  it("combines search + sort + filters", () => {
    const summary = buildActiveFilterSummary(
      { status: "draft", validation_status: "valid", has_route: "all" },
      "beta",
      1,
    );
    expect(summary.count).toBe(4);
    expect(summary.labels).toContain("Поиск");
    expect(summary.labels).toContain("Сортировка: 1");
    expect(summary.labels).toContain("Статус");
    expect(summary.labels).toContain("Валидация");
    expect(summary.labels).not.toContain("Маршрут");
  });

  it("maps filter keys to short Russian labels", () => {
    const summary = buildActiveFilterSummary(
      {
        status: "all",
        validation_status: "invalid",
        has_route: "yes",
        has_errors: "yes",
        has_warnings: "no",
        has_duplicates: "yes",
      },
      "",
      0,
    );
    expect(summary.count).toBe(5);
    expect(summary.labels).toContain("Валидация");
    expect(summary.labels).toContain("Маршрут");
    expect(summary.labels).toContain("Ошибки");
    expect(summary.labels).toContain("Предупр.");
    expect(summary.labels).toContain("Дубликаты");
  });

  it("falls back to key name for unknown filter keys", () => {
    const summary = buildActiveFilterSummary(
      { custom_filter: "active" },
      "",
      0,
    );
    expect(summary.count).toBe(1);
    expect(summary.labels).toContain("custom_filter");
  });
});
