const test = require("node:test");
const assert = require("node:assert/strict");
const { buildStepCommand } = require("./gate-command-core.js");

test("шаг без honorsStrict не получает флаг даже в strict", () => {
  assert.equal(buildStepCommand({ command: "npm run check:docs" }, true), "npm run check:docs");
});

test("strict вне силы для команды, которая и без того не меняется", () => {
  assert.equal(
    buildStepCommand({ command: "node scripts/freshness.js", honorsStrict: true }, false),
    "node scripts/freshness.js",
  );
});

test("прямая команда получает --strict как есть", () => {
  assert.equal(
    buildStepCommand({ command: "node scripts/codegraph-age.mjs", honorsStrict: true }, true),
    "node scripts/codegraph-age.mjs --strict",
  );
});

test("npm-команда получает флаг за разделителем: иначе npm съедает его сам", () => {
  assert.equal(
    buildStepCommand({ command: "npm run check:freshness", honorsStrict: true }, true),
    "npm run check:freshness -- --strict",
  );
});

test("npm-обёртка с префиксом тоже получает разделитель", () => {
  assert.equal(
    buildStepCommand({ command: "npm --prefix frontend run check:x", honorsStrict: true }, true),
    "npm --prefix frontend run check:x -- --strict",
  );
});
