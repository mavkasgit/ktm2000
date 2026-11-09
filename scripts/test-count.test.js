/**
 * Пробник #358: рэтчет числа тестов обязан краснеть на уменьшение и не краснеть
 * на рост, а разбор — замечать смену формата сборщика.
 *
 * Проверются чистые функции из test-count-core.js на снятых выводах реальных
 * сборщиков (`pytest --collect-only -q`, `vitest list`): сборщик в тесте не
 * запускается, он стоит минут, а его надёжность — предмет шагов backend-tests и
 * frontend-unit, не этого файла.
 *
 * Запуск: npm run test:scripts.
 */

"use strict";

const test = require("node:test");
const assert = require("node:assert/strict");

const {
  parsePytestCollect,
  parseVitestList,
  parseVitestJson,
  findReductions,
  evaluateStored,
} = require("./test-count-core.js");

const PYTEST = [
  "tests/transfers/test_budget.py::test_plain_transfer_budget_excludes_received",
  "tests/transfers/test_budget.py::test_correct_transfer_returns_old_quantity_once",
  "tests/test_shopfloor_api.py::test_finish_creates_stock[2-1]",
  "",
  "3 tests collected in 1.34s",
  "",
].join("\r\n");

test("pytest: id-строки и итог собраны в числа по файлам", () => {
  const out = parsePytestCollect(PYTEST);
  assert.equal(out.ok, true);
  assert.equal(out.total, 3);
  assert.deepEqual(out.by_file, {
    "tests/transfers/test_budget.py": 2,
    "tests/test_shopfloor_api.py": 1,
  });
});

test("pytest: итог не сходится с числом id-строк — красный, а не «посчитаем что удалось»", () => {
  const out = parsePytestCollect(PYTEST.replace("3 tests collected", "9 tests collected"));
  assert.equal(out.ok, false);
  assert.match(out.reason, /итог говорит 9, id-строк 3/);
});

test("pytest: нераспознанная строка — красный с этой строкой (формат сборщика поменялся)", () => {
  const out = parsePytestCollect(`tests/test_a.py::test_one\n<Dir backend>\n\n1 test collected in 0.10s`);
  assert.equal(out.ok, false);
  assert.match(out.reason, /не разобран/);
  assert.deepEqual(out.anomalies, ["<Dir backend>"]);
});

test("pytest: нет итоговой строки — красный (обрезанный вывод не считается нулём)", () => {
  const out = parsePytestCollect("tests/test_a.py::test_one\n");
  assert.equal(out.ok, false);
  assert.match(out.reason, /нет итоговой строки/);
});

test("vitest: группировка по файлам, .mjs-тесты считаются наравне с .tsx", () => {
  const out = parseVitestList(
    [
      "src/features/references/pages/RawMaterialsPage.test.tsx > меню «Операции» > открывается по клику",
      "src/features/references/pages/RawMaterialsPage.test.tsx > меню «Операции» > экспорт вызывает функцию",
      "scripts/verify-sync.test.mjs > verify-sync.mjs > match → ok (exit 0)",
    ].join("\n"),
  );
  assert.equal(out.ok, true);
  assert.equal(out.total, 3);
  assert.deepEqual(out.by_file, {
    "src/features/references/pages/RawMaterialsPage.test.tsx": 2,
    "scripts/verify-sync.test.mjs": 1,
  });
});

test("vitest: пустая выдача — красный, это сломанный сбор, а не «ноль тестов»", () => {
  const out = parseVitestList("\n\n");
  assert.equal(out.ok, false);
  assert.match(out.reason, /ни одного теста/);
});

test("vitest JSON: считает развёрнутые each-кейсы и нормализует пути", () => {
  const report = JSON.stringify({
    numTotalTests: 3,
    testResults: [
      { name: "C:/repo/frontend/src/a.test.ts", assertionResults: [{}, {}] },
      { name: "C:/repo/frontend/scripts/b.test.mjs", assertionResults: [{}] },
    ],
  });
  const out = parseVitestJson(report, "C:/repo/frontend");
  assert.equal(out.ok, true);
  assert.equal(out.total, 3);
  assert.deepEqual(out.by_file, { "src/a.test.ts": 2, "scripts/b.test.mjs": 1 });
});

test("vitest JSON: итог не сходится с assertionResults — красный", () => {
  const report = JSON.stringify({
    numTotalTests: 9,
    testResults: [{ name: "C:/repo/frontend/src/a.test.ts", assertionResults: [{}] }],
  });
  const out = parseVitestJson(report, "C:/repo/frontend");
  assert.equal(out.ok, false);
  assert.match(out.reason, /итог говорит 9, assertionResults 1/);
});

test("vitest JSON: битый JSON — красный", () => {
  const out = parseVitestJson("{not json", "C:/repo/frontend");
  assert.equal(out.ok, false);
  assert.match(out.reason, /JSON vitest не разобран/);
});

test("vitest: строка без разделителя сютов — красный (вывод меняется, парсер обязан это увидеть)", () => {
  const out = parseVitestList("src/app/Page.test.tsx\n1 test file found\n");
  assert.equal(out.ok, false);
  assert.match(out.reason, /не разобран/);
});

test("рэтчет: завышенный минимум краснеет и показывает пропавшие файлы (критерий в)", () => {
  const stored = { total: 10, by_file: { "tests/test_a.py": 7, "tests/test_b.py": 3 } };
  const current = { total: 5, by_file: { "tests/test_a.py": 5 } };
  const out = evaluateStored(stored, current);
  assert.equal(out.ok, false);
  assert.equal(out.reason, "собрано меньше минимума: 10 → 5");
  assert.deepEqual(out.reductions, [
    { file: "tests/test_b.py", before: 3, after: 0 },
    { file: "tests/test_a.py", before: 7, after: 5 },
  ]);
});

test("рэтчет: заниженный минимум зелёный — рэтчет не требует равенства (критерий в)", () => {
  const stored = { total: 2, by_file: { "tests/test_a.py": 2 } };
  const current = { total: 5, by_file: { "tests/test_a.py": 5 } };
  assert.equal(evaluateStored(stored, current).ok, true);
});

test("рэтчет: итог ровный, но тесты переехали в другой файл — всё равно красный", () => {
  const stored = { total: 4, by_file: { "tests/test_old.py": 4 } };
  const current = { total: 4, by_file: { "tests/test_new.py": 4 } };
  const out = evaluateStored(stored, current);
  assert.equal(out.ok, false);
  assert.match(out.reason, /итог не изменился/);
  assert.deepEqual(out.reductions, [{ file: "tests/test_old.py", before: 4, after: 0 }]);
});

test("Редукция считает только уменьшения; рост и новые файлы — не находка", () => {
  const stored = { "tests/test_a.py": 1, "tests/test_b.py": 4 };
  const current = { "tests/test_a.py": 9, "tests/test_b.py": 4, "tests/test_new.py": 2 };
  assert.deepEqual(findReductions(stored, current), []);
});
