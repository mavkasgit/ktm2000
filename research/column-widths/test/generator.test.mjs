import assert from "node:assert/strict";
import test from "node:test";

import { buildColumns } from "../lib/columns.mjs";
import { PROFILES, generateSheet } from "../lib/generator.mjs";

for (const profile of PROFILES) {
  test(`генератор ${profile} детерминирован по seed`, () => {
    const columns = buildColumns(11);
    const first = generateSheet({ profile, rows: 50, columns, seed: 42 });
    const second = generateSheet({ profile, rows: 50, columns, seed: 42 });
    const other = generateSheet({ profile, rows: 50, columns, seed: 43 });
    assert.deepEqual(first.rows, second.rows);
    assert.notDeepEqual(first.rows, other.rows);
  });
}

test("наборы колонок соответствуют 6/11/12/20", () => {
  assert.equal(buildColumns(6).length, 6);
  assert.equal(buildColumns(11).length, 11);
  assert.equal(buildColumns(12).length, 12);
  assert.equal(buildColumns(20).length, 20);
  assert.ok(buildColumns(6).some((column) => column.id === "source_name"));
  assert.ok(buildColumns(6).some((column) => column.id === "operations"));
});

test("в профиле outlier есть длинная ячейка, в all-short — короткие", () => {
  const columns = buildColumns(11);
  const outlier = generateSheet({ profile: "outlier", rows: 20, columns, seed: 1 });
  const longNames = outlier.rows.filter(
    (row) => String(row.values.source_name).length > 100,
  );
  assert.ok(longNames.length >= 1);

  const short = generateSheet({ profile: "all-short", rows: 20, columns, seed: 1 });
  for (const row of short.rows) {
    assert.ok(String(row.values.source_name).length <= 25);
  }
});

test("профиль empty действительно оставляет пустые значения", () => {
  const columns = buildColumns(11);
  const sheet = generateSheet({ profile: "empty", rows: 100, columns, seed: 5 });
  const empty = sheet.rows.filter((row) => row.values.source_name === "");
  assert.ok(empty.length > 0);
});
