import assert from "node:assert/strict";
import test from "node:test";

import { buildColumns } from "../lib/columns.mjs";
import {
  ALL_SHORT_MAX_LENGTH,
  CALIBRATION,
  MAX_NAME_LENGTH,
  OUTLIER_PILL_COUNT,
  OUTLIER_TEXT_MIN_LENGTH,
  PROFILES,
  generateSheet,
} from "../lib/generator.mjs";

const SEED = 7;

function percentile(values, p) {
  const sorted = [...values].sort((a, b) => a - b);
  assert.ok(sorted.length > 0, "перцентиль по пустому набору");
  const index = (sorted.length - 1) * p;
  const lower = Math.floor(index);
  const upper = Math.min(lower + 1, sorted.length - 1);
  return sorted[lower] + (sorted[upper] - sorted[lower]) * (index - lower);
}

function cellLengths(sheet, columnId) {
  return sheet.rows.map((row) => String(row.values[columnId] ?? "").length);
}

function errorLengths(sheet) {
  return sheet.rows
    .map((row) => String(row.values.errors ?? ""))
    .filter((value) => value.length > 0)
    .map((value) => value.length);
}

function near(actual, target, tolerance) {
  return Math.abs(actual - target) <= tolerance;
}

test("объявлены ровно 7 профилей", () => {
  assert.equal(PROFILES.length, 7);
  assert.deepEqual(new Set(PROFILES).size, 7);
  assert.deepEqual(PROFILES, [
    "realistic",
    "long-tail",
    "outlier",
    "all-short",
    "mono",
    "mixed",
    "empty",
  ]);
});

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

test("размеры 100 / 1000 / 5000 строк генерируются целиком", () => {
  const columns = buildColumns(11);
  for (const rows of [100, 1000, 5000]) {
    const sheet = generateSheet({ profile: "realistic", rows, columns, seed: 1 });
    assert.equal(sheet.rows.length, rows);
    for (const row of sheet.rows) {
      assert.equal(Object.keys(row.values).length, columns.length);
    }
  }
});

test("наборы колонок 6 / 11 / 12 / 20 согласованы с генератором", () => {
  for (const count of [6, 11, 12, 20]) {
    const columns = buildColumns(count);
    assert.equal(columns.length, count);
    assert.equal(new Set(columns.map((column) => column.id)).size, count);
    const sheet = generateSheet({ profile: "realistic", rows: 100, columns, seed: 1 });
    for (const row of sheet.rows) {
      for (const column of columns) {
        assert.notEqual(row.values[column.id], undefined, `${count}: ${column.id}`);
      }
    }
  }

  const six = buildColumns(6);
  assert.ok(six.some((column) => column.id === "source_name"));
  assert.ok(six.some((column) => column.id === "operations"));
  assert.ok(six.every((column) => !column.id.startsWith("extra_")));

  const twelve = buildColumns(12);
  assert.equal(twelve.filter((column) => column.id.startsWith("extra_")).length, 1);
  const twenty = buildColumns(20);
  assert.equal(twenty.filter((column) => column.id.startsWith("extra_")).length, 9);
});

test("realistic откалиброван по реальным наименованиям, артикулам и ошибкам", () => {
  const sheet = generateSheet({
    profile: "realistic",
    rows: 2000,
    columns: buildColumns(11),
    seed: SEED,
  });

  const names = cellLengths(sheet, "source_name");
  assert.ok(near(percentile(names, 0.5), CALIBRATION.name.p50, 6), "name p50");
  assert.ok(near(percentile(names, 0.9), CALIBRATION.name.p90, 8), "name p90");
  assert.ok(near(percentile(names, 0.99), CALIBRATION.name.p99, 15), "name p99");
  assert.ok(Math.max(...names) <= MAX_NAME_LENGTH, "имя не должно само быть выбросом");

  const skus = cellLengths(sheet, "sku");
  assert.ok(near(percentile(skus, 0.5), CALIBRATION.sku.p50, 4), "sku p50");
  assert.ok(near(percentile(skus, 0.99), CALIBRATION.sku.p99, 4), "sku p99");
  assert.ok(Math.max(...skus) <= 15, "артикул без суффикса не длиннее 15");

  const errors = errorLengths(sheet);
  assert.ok(errors.length > 50, "в выборке должно быть достаточно ошибок");
  assert.ok(near(percentile(errors, 0.5), CALIBRATION.errors.p50, 12), "errors p50");
  assert.ok(near(percentile(errors, 0.9), CALIBRATION.errors.p90, 15), "errors p90");
  assert.ok(near(percentile(errors, 0.99), CALIBRATION.errors.p99, 10), "errors p99");
});

test("outlier даёт ровно один выброс на текстовую колонку", () => {
  const sheet = generateSheet({
    profile: "outlier",
    rows: 200,
    columns: buildColumns(20),
    seed: 3,
  });

  const textColumns = sheet.columns.filter((column) => column.kind === "text");
  assert.ok(textColumns.length >= 11, "в наборе 20 колонок есть generic-текст");
  for (const column of textColumns) {
    const outliers = sheet.rows.filter(
      (row) => String(row.values[column.id] ?? "").length >= OUTLIER_TEXT_MIN_LENGTH,
    );
    assert.equal(outliers.length, 1, `выброс в ${column.id}`);
    assert.equal(sheet.rows.indexOf(outliers[0]), 0, `выброс в ${column.id} — первая строка`);
  }

  const widePills = sheet.rows.filter((row) => row.values.operations.length >= OUTLIER_PILL_COUNT);
  assert.equal(widePills.length, 1);
  for (const row of sheet.rows.slice(1)) {
    assert.ok(row.values.operations.length < OUTLIER_PILL_COUNT);
  }

  for (const id of ["sku", "source_code"]) {
    const tooLong = sheet.rows.filter(
      (row) => String(row.values[id] ?? "").length >= OUTLIER_TEXT_MIN_LENGTH,
    );
    assert.equal(tooLong.length, 0, `mono-колонка ${id} не получает выброс`);
  }
});

test("all-short не содержит значений длиннее 25 символов", () => {
  const sheet = generateSheet({
    profile: "all-short",
    rows: 200,
    columns: buildColumns(20),
    seed: 1,
  });

  let nonEmpty = 0;
  for (const row of sheet.rows) {
    for (const column of sheet.columns) {
      const value = row.values[column.id];
      if (Array.isArray(value)) {
        for (const pill of value) {
          assert.ok(pill.length <= ALL_SHORT_MAX_LENGTH, `${column.id}: ${pill}`);
          nonEmpty += 1;
        }
      } else {
        assert.ok(
          String(value).length <= ALL_SHORT_MAX_LENGTH,
          `${column.id}: ${String(value)}`,
        );
        if (String(value).length > 0) nonEmpty += 1;
      }
    }
  }
  assert.ok(nonEmpty > 0, "профиль не должен быть пустым");
});

test("mono даёт артикулы без пробелов", () => {
  const sheet = generateSheet({
    profile: "mono",
    rows: 200,
    columns: buildColumns(11),
    seed: 1,
  });

  for (const row of sheet.rows) {
    const sku = String(row.values.sku);
    assert.ok(!/\s/.test(sku), `пробел в артикуле: ${sku}`);
    assert.ok(sku.length >= 12, `короткий артикул: ${sku}`);
    assert.ok(!/\s/.test(String(row.values.source_code)));
  }
});

test("empty покрывает пустые значения и пустые пилюли операций", () => {
  const sheet = generateSheet({
    profile: "empty",
    rows: 300,
    columns: buildColumns(11),
    seed: 5,
  });

  const nameEmpty = sheet.rows.filter((row) => row.values.source_name === "").length;
  assert.ok(nameEmpty > 0.15 * sheet.rows.length, "доля пустых наименований");
  assert.ok(nameEmpty < 0.45 * sheet.rows.length, "пустые значения не должны быть нормой");

  for (const column of sheet.columns) {
    if (column.kind === "pills") continue;
    assert.ok(
      sheet.rows.some((row) => row.values[column.id] === ""),
      `нет пустого значения в ${column.id}`,
    );
  }

  const emptyPills = sheet.rows.filter((row) => row.values.operations.length === 0).length;
  assert.ok(emptyPills > 0, "нет пустых пилюль операций");
  assert.ok(emptyPills < sheet.rows.length, "все пилюли пустыми быть не должны");
  assert.ok(
    sheet.rows.some((row) => row.values.operations.length > 0),
    "пустые пилюли не должны вытеснить непустые",
  );
});

test("профили дают разные стресс-условия", () => {
  const columns = buildColumns(11);
  const realistic = generateSheet({ profile: "realistic", rows: 500, columns, seed: SEED });
  const longTail = generateSheet({ profile: "long-tail", rows: 500, columns, seed: SEED });
  const allShort = generateSheet({ profile: "all-short", rows: 500, columns, seed: SEED });
  const mixed = generateSheet({ profile: "mixed", rows: 500, columns, seed: SEED });
  const empty = generateSheet({ profile: "empty", rows: 500, columns, seed: SEED });
  const outlier = generateSheet({ profile: "outlier", rows: 500, columns, seed: SEED });

  assert.ok(
    percentile(cellLengths(longTail, "source_name"), 0.9) >
      2 * percentile(cellLengths(realistic, "source_name"), 0.9),
    "long-tail должен быть заметно длиннее realistic",
  );
  assert.ok(
    percentile(cellLengths(allShort, "source_name"), 0.9) <
      0.7 * percentile(cellLengths(realistic, "source_name"), 0.9),
    "all-short должен быть заметно короче realistic",
  );

  const avg = (values) => values.reduce((sum, value) => sum + value, 0) / values.length;
  assert.ok(
    avg(cellLengths(mixed, "source_name")) > avg(cellLengths(allShort, "source_name")),
    "mixed не должен схлопываться в all-short",
  );
  const mixedValues = mixed.rows.map((row) => String(row.values.source_name));
  assert.ok(mixedValues.some((value) => /[A-Za-z]/.test(value)), "в mixed есть латиница");
  assert.ok(mixedValues.some((value) => /[А-Яа-яЁё]/.test(value)), "в mixed есть кириллица");

  assert.equal(
    empty.rows.filter((row) => row.values.source_name === "").length > 0,
    true,
    "empty содержит пустые значения",
  );
  assert.equal(
    realistic.rows.filter((row) => row.values.source_name === "").length,
    0,
    "realistic не содержит пустых значений",
  );

  assert.ok(
    Math.max(...cellLengths(outlier, "source_name")) >= OUTLIER_TEXT_MIN_LENGTH,
    "outlier содержит длинную ячейку",
  );
  assert.ok(
    Math.max(...cellLengths(realistic, "source_name")) < OUTLIER_TEXT_MIN_LENGTH,
    "realistic обходится без выбросов",
  );
});

test("5000 строк генерируются быстрее секунды и без лишней памяти", () => {
  const columns = buildColumns(12);
  generateSheet({ profile: "realistic", rows: 100, columns, seed: 1 }); // прогрев JIT

  const before = process.memoryUsage().heapUsed;
  const started = performance.now();
  const sheet = generateSheet({ profile: "realistic", rows: 5000, columns, seed: 1 });
  const elapsed = performance.now() - started;
  const allocated = process.memoryUsage().heapUsed - before;

  assert.equal(sheet.rows.length, 5000);
  assert.ok(elapsed < 1000, `5000 строк за ${elapsed.toFixed(0)} мс`);
  assert.ok(allocated < 128 * 1024 * 1024, `лист занял ${(allocated / 1024 / 1024).toFixed(1)} МБ`);
});
