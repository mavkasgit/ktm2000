import { describe, expect, it } from "vitest";

import {
  nextImportPreviewSortConfig,
  sortImportPreviewRows,
  type ImportPreviewRow,
} from "./importPreviewSort";

/** Превью-строка с меткой в after_data — по ней проверяется порядок строк. */
function row(marker: string, overrides: Partial<ImportPreviewRow> = {}): ImportPreviewRow {
  return { after_data: { marker }, ...overrides };
}

const order = (rows: ImportPreviewRow[]): string[] =>
  rows.map((r) => String((r.after_data as Record<string, unknown>).marker));

describe("sortImportPreviewRows — «Строка» (source_row_number)", () => {
  const rows = [
    row("ten", { source_row_number: 10 }),
    row("nine", { source_row_number: 9 }),
    row("hundred", { source_row_number: 100 }),
    row("two", { source_row_number: 2 }),
  ];

  it("по возрастанию: 2, 9, 10, 100 — сравнение чисел, а не строк", () => {
    const sorted = sortImportPreviewRows(rows, { key: "source_row_number", dir: "asc" });
    expect(order(sorted)).toEqual(["two", "nine", "ten", "hundred"]);
  });

  it("по убыванию: 100, 10, 9, 2", () => {
    const sorted = sortImportPreviewRows(rows, { key: "source_row_number", dir: "desc" });
    expect(order(sorted)).toEqual(["hundred", "ten", "nine", "two"]);
  });

  it("строка без номера уходит в конец при любом направлении", () => {
    const withGap = [...rows, row("gap")];
    expect(order(sortImportPreviewRows(withGap, { key: "source_row_number", dir: "asc" }))).toEqual([
      "two",
      "nine",
      "ten",
      "hundred",
      "gap",
    ]);
    expect(order(sortImportPreviewRows(withGap, { key: "source_row_number", dir: "desc" }))).toEqual([
      "hundred",
      "ten",
      "nine",
      "two",
      "gap",
    ]);
  });

  it("объединённые строки читаются по source_row_numbers из after_data", () => {
    const merged = [row("b", { after_data: { marker: "b", source_row_numbers: [12, 3] } }), row("a", { after_data: { marker: "a", source_row_numbers: [2] } })];
    expect(order(sortImportPreviewRows(merged, { key: "source_row_number", dir: "asc" }))).toEqual([
      "a",
      "b",
    ]);
  });
});

describe("sortImportPreviewRows — «Кол-во» (quantity)", () => {
  const rows = [
    row("ten", { after_data: { marker: "ten", quantity: 10 } }),
    row("nine", { after_data: { marker: "nine", quantity: 9 } }),
    row("hundred", { after_data: { marker: "hundred", quantity: 100 } }),
    // Количество приходит и строкой из Excel — тоже сравнивается как число.
    row("str-two", { after_data: { marker: "str-two", quantity: "2" } }),
  ];

  it("по возрастанию: 2, 9, 10, 100", () => {
    expect(order(sortImportPreviewRows(rows, { key: "quantity", dir: "asc" }))).toEqual([
      "str-two",
      "nine",
      "ten",
      "hundred",
    ]);
  });

  it("по убыванию: 100, 10, 9, 2", () => {
    expect(order(sortImportPreviewRows(rows, { key: "quantity", dir: "desc" }))).toEqual([
      "hundred",
      "ten",
      "nine",
      "str-two",
    ]);
  });
});

describe("sortImportPreviewRows — «Ошибки» и «Предупр.»", () => {
  it("сортирует по количеству кодов, а не по склейке кодов", () => {
    const rows = [
      row("three", { errors: ["zzz_error", "yyy_error", "aaa_error"] }),
      row("one", { errors: ["zzz_error"] }),
      row("two", { errors: ["aaa_error", "bbb_error"] }),
      row("none", { errors: [] }),
    ];

    // Склейка кодов дала бы «aaa,bbb» раньше «zzz» — то есть 2 ошибки перед 1.
    expect(order(sortImportPreviewRows(rows, { key: "errors", dir: "asc" }))).toEqual([
      "none",
      "one",
      "two",
      "three",
    ]);
    expect(order(sortImportPreviewRows(rows, { key: "errors", dir: "desc" }))).toEqual([
      "three",
      "two",
      "one",
      "none",
    ]);
  });

  it("предупреждения сортируются независимо от ошибок", () => {
    const rows = [
      row("three", { warnings: ["w1", "w2", "w3"] }),
      row("one", { warnings: ["w1"] }),
      row("two", { warnings: ["w1", "w2"] }),
    ];

    expect(order(sortImportPreviewRows(rows, { key: "warnings", dir: "asc" }))).toEqual([
      "one",
      "two",
      "three",
    ]);
  });
});

describe("sortImportPreviewRows — текстовые колонки", () => {
  it("артикулы сравниваются натурально: ЮП-2 раньше ЮП-10", () => {
    const rows = [
      row("ten", { after_data: { marker: "ten", source_sku: "ЮП-10" } }),
      row("two", { after_data: { marker: "two", source_sku: "ЮП-2" } }),
    ];
    expect(order(sortImportPreviewRows(rows, { key: "source_sku", dir: "asc" }))).toEqual([
      "two",
      "ten",
    ]);
  });

  it("наименование и маршрут сортируются по алфавиту в обоих направлениях", () => {
    const rows = [
      row("b", { after_data: { marker: "b", source_name: "Брус", route_name: "Резка" } }),
      row("a", { after_data: { marker: "a", source_name: "Алюминий", route_name: "Сварка" } }),
    ];
    expect(order(sortImportPreviewRows(rows, { key: "source_name", dir: "asc" }))).toEqual(["a", "b"]);
    expect(order(sortImportPreviewRows(rows, { key: "source_name", dir: "desc" }))).toEqual(["b", "a"]);
    expect(order(sortImportPreviewRows(rows, { key: "route_name", dir: "asc" }))).toEqual(["b", "a"]);
  });
});

describe("sortImportPreviewRows — без сортировки", () => {
  it("null сохраняет порядок строк как есть и не мутирует исходный массив", () => {
    const rows = [row("c"), row("a"), row("b")];
    expect(order(sortImportPreviewRows(rows, null))).toEqual(["c", "a", "b"]);
    expect(order(rows)).toEqual(["c", "a", "b"]);
  });
});

describe("nextImportPreviewSortConfig", () => {
  it("цикл клика: нет сортировки → убывание → возрастание → нет", () => {
    const first = nextImportPreviewSortConfig(null, "source_row_number");
    expect(first).toEqual({ key: "source_row_number", dir: "desc" });

    const second = nextImportPreviewSortConfig(first, "source_row_number");
    expect(second).toEqual({ key: "source_row_number", dir: "asc" });

    expect(nextImportPreviewSortConfig(second, "source_row_number")).toBeNull();
  });

  it("переход на другую колонку начинает с убывания", () => {
    const byRow = nextImportPreviewSortConfig(null, "source_row_number");
    expect(nextImportPreviewSortConfig(byRow, "quantity")).toEqual({ key: "quantity", dir: "desc" });
  });
});
