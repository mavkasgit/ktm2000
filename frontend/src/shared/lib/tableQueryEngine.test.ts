import { describe, it, expect } from "vitest";
import { buildSearchIndex, processTableRows, SortConfig, ColumnSortDef } from "./tableQueryEngine";

type TestRow = {
  id: number;
  name: string;
  status: string;
  qty: number;
  payload?: Record<string, unknown> | null;
};

const makeSortDefs = (): ColumnSortDef<TestRow, "id" | "name" | "status" | "qty">[] => [
  { field: "id", getSortValue: (r) => r.id },
  { field: "name", getSortValue: (r) => r.name },
  { field: "status", getSortValue: (r) => r.status },
  { field: "qty", getSortValue: (r) => r.qty },
];

const makeRows = (): TestRow[] => [
  { id: 1, name: "Alpha", status: "draft", qty: 10 },
  { id: 2, name: "Beta", status: "valid", qty: 5 },
  { id: 3, name: "Gamma", status: "draft", qty: 20 },
  { id: 4, name: "Delta", status: "invalid", qty: 0 },
  { id: 5, name: "Alpha Two", status: "valid", qty: 15, payload: { nested: "secret_value" } },
];

describe("buildSearchIndex", () => {
  it("flattens all fields into searchable string", () => {
    const row = { id: 1, name: "Test", status: "draft", qty: 10 };
    const index = buildSearchIndex(row);
    expect(index).toContain("test");
    expect(index).toContain("draft");
    expect(index).toContain("10");
  });

  it("includes nested payload values", () => {
    const row = { id: 5, name: "Alpha Two", status: "valid", qty: 15, payload: { nested: "secret_value" } };
    const index = buildSearchIndex(row);
    expect(index).toContain("secret_value");
  });

  it("respects searchKeys when provided", () => {
    const row = { id: 1, name: "Test", status: "draft", qty: 10 };
    const index = buildSearchIndex(row, ["name"]);
    expect(index).toContain("test");
    expect(index).not.toContain("draft");
  });

  it("handles null/undefined gracefully", () => {
    const row = { id: 1, name: null as unknown as string, status: undefined as unknown as string };
    const index = buildSearchIndex(row);
    expect(typeof index).toBe("string");
  });

  it("normalizes ru text (e.g. ё -> е) for search", () => {
    const row = { id: 7, name: "Ёлка", status: "valid", qty: 1 };
    const index = buildSearchIndex(row);
    expect(index).toContain("елка");
  });
});

describe("processTableRows", () => {
  const rows = makeRows();
  const sortDefs = makeSortDefs();

  function buildIndex(rows: TestRow[]): Map<string, string> {
    const map = new Map<string, string>();
    for (const row of rows) {
      map.set(String(row.id), buildSearchIndex(row));
    }
    return map;
  }

  const searchIndex = buildIndex(rows);

  it("returns all rows when no query or filter", () => {
    const result = processTableRows({
      rows,
      searchQuery: "",
      searchIndex,
      filterPredicate: null,
      sortConfigs: [],
      sortDefs: new Map(sortDefs.map((d) => [d.field, d])),
    });
    expect(result.rows).toHaveLength(5);
    expect(result.totalCount).toBe(5);
    expect(result.filteredCount).toBe(5);
  });

  it("searches by any field value", () => {
    const result = processTableRows({
      rows,
      searchQuery: "beta",
      searchIndex,
      filterPredicate: null,
      sortConfigs: [],
      sortDefs: new Map(sortDefs.map((d) => [d.field, d])),
    });
    expect(result.rows).toHaveLength(1);
    expect(result.rows[0].name).toBe("Beta");
  });

  it("searches within nested payload", () => {
    const result = processTableRows({
      rows,
      searchQuery: "secret_value",
      searchIndex,
      filterPredicate: null,
      sortConfigs: [],
      sortDefs: new Map(sortDefs.map((d) => [d.field, d])),
    });
    expect(result.rows).toHaveLength(1);
    expect(result.rows[0].id).toBe(5);
  });

  it("applies filter predicate", () => {
    const result = processTableRows({
      rows,
      searchQuery: "",
      searchIndex,
      filterPredicate: (r) => r.status === "draft",
      sortConfigs: [],
      sortDefs: new Map(sortDefs.map((d) => [d.field, d])),
    });
    expect(result.rows).toHaveLength(2);
    // filteredCount is post-search, pre-filter count (no search query means all rows pass search)
    expect(result.filteredCount).toBe(5);
  });

  it("sorts ascending by field", () => {
    const result = processTableRows({
      rows,
      searchQuery: "",
      searchIndex,
      filterPredicate: null,
      sortConfigs: [{ field: "name", order: "asc" }],
      sortDefs: new Map(sortDefs.map((d) => [d.field, d])),
    });
    const names = result.rows.map((r) => r.name);
    expect(names).toEqual(["Alpha", "Alpha Two", "Beta", "Delta", "Gamma"]);
  });

  it("sorts descending by field", () => {
    const result = processTableRows({
      rows,
      searchQuery: "",
      searchIndex,
      filterPredicate: null,
      sortConfigs: [{ field: "qty", order: "desc" }],
      sortDefs: new Map(sortDefs.map((d) => [d.field, d])),
    });
    const qtys = result.rows.map((r) => r.qty);
    expect(qtys).toEqual([20, 15, 10, 5, 0]);
  });

  it("multi-sort respects priority order", () => {
    const result = processTableRows({
      rows,
      searchQuery: "",
      searchIndex,
      filterPredicate: null,
      sortConfigs: [
        { field: "status", order: "asc" },
        { field: "id", order: "desc" },
      ],
      sortDefs: new Map(sortDefs.map((d) => [d.field, d])),
    });
    // status asc: draft(1,3), invalid(4), valid(2,5)
    // within same status, id desc: draft -> 3,1; valid -> 5,2
    const ids = result.rows.map((r) => r.id);
    expect(ids).toEqual([3, 1, 4, 5, 2]);
  });

  it("handles empty rows array", () => {
    const result = processTableRows({
      rows: [],
      searchQuery: "anything",
      searchIndex: new Map(),
      filterPredicate: null,
      sortConfigs: [],
      sortDefs: new Map(),
    });
    expect(result.rows).toHaveLength(0);
    expect(result.totalCount).toBe(0);
  });

  it("search + filter pipeline order is correct", () => {
    // Search first, then filter
    const result = processTableRows({
      rows,
      searchQuery: "alpha", // matches id=1 and id=5
      searchIndex,
      filterPredicate: (r) => r.status === "draft", // only id=1 is draft
      sortConfigs: [],
      sortDefs: new Map(sortDefs.map((d) => [d.field, d])),
    });
    expect(result.rows).toHaveLength(1);
    expect(result.rows[0].id).toBe(1);
  });

  it("handles null values in sort fields", () => {
    const rowsWithNulls: TestRow[] = [
      { id: 1, name: "Alpha", status: "draft", qty: 10 },
      { id: 2, name: "", status: "valid", qty: 5 },
      { id: 3, name: null as unknown as string, status: "draft", qty: 20 },
    ];
    const index = buildIndex(rowsWithNulls);
    const result = processTableRows({
      rows: rowsWithNulls,
      searchQuery: "",
      searchIndex: index,
      filterPredicate: null,
      sortConfigs: [{ field: "name", order: "asc" }],
      sortDefs: new Map(sortDefs.map((d) => [d.field, d])),
    });
    // Empty/null values should be pushed to the end
    expect(result.rows[0].name).toBe("Alpha");
  });

  it("sorts mixed alphanumeric strings naturally", () => {
    const rowsMixed: TestRow[] = [
      { id: 1, name: "item10", status: "valid", qty: 1 },
      { id: 2, name: "item2", status: "valid", qty: 1 },
      { id: 3, name: "item1", status: "valid", qty: 1 },
    ];
    const index = buildIndex(rowsMixed);
    const result = processTableRows({
      rows: rowsMixed,
      searchQuery: "",
      searchIndex: index,
      filterPredicate: null,
      sortConfigs: [{ field: "name", order: "asc" }],
      sortDefs: new Map(sortDefs.map((d) => [d.field, d])),
    });

    expect(result.rows.map((r) => r.name)).toEqual(["item1", "item2", "item10"]);
  });

  it("keeps stable order for equal sort keys", () => {
    const rowsStable: TestRow[] = [
      { id: 10, name: "Same", status: "draft", qty: 1 },
      { id: 11, name: "Same", status: "draft", qty: 2 },
      { id: 12, name: "Same", status: "draft", qty: 3 },
    ];
    const index = buildIndex(rowsStable);
    const result = processTableRows({
      rows: rowsStable,
      searchQuery: "",
      searchIndex: index,
      filterPredicate: null,
      sortConfigs: [{ field: "name", order: "asc" }],
      sortDefs: new Map(sortDefs.map((d) => [d.field, d])),
    });

    expect(result.rows.map((r) => r.id)).toEqual([10, 11, 12]);
  });

  it("matches normalized query against normalized index", () => {
    const rowsRu: TestRow[] = [
      { id: 1, name: "Ежик", status: "valid", qty: 1 },
      { id: 2, name: "Тест", status: "valid", qty: 1 },
    ];
    const index = buildIndex(rowsRu);
    const result = processTableRows({
      rows: rowsRu,
      searchQuery: "ЁЖИК",
      searchIndex: index,
      filterPredicate: null,
      sortConfigs: [],
      sortDefs: new Map(sortDefs.map((d) => [d.field, d])),
    });

    expect(result.rows).toHaveLength(1);
    expect(result.rows[0].id).toBe(1);
  });
});
