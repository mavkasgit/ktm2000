"use strict";
// Датированные исключения аудита зависимостей (#369): запись без причины или с
// прошедшей датой пересмотра — красный шаг. Проверка обязана уметь падать.
const test = require("node:test");
const assert = require("node:assert/strict");

const { validateEntries, toOsvToml, parseDate } = require("./osv-allowlist.mjs");

const TODAY = new Date("2026-11-18T00:00:00Z");
const entry = (over = {}) => ({
  id: "GHSA-aaaa-bbbb-cccc",
  package: "example@1.0.0",
  reason: "уязвимость не в досягаемом пути; обновление ломает API",
  review_by: "2027-01-01",
  ...over,
});

test("валидная запись с будущей датой пересмотра проходит", () => {
  assert.deepEqual(validateEntries([entry()], TODAY), []);
});

test("просроченная запись краснеет и называет id", () => {
  const errors = validateEntries([entry({ review_by: "2026-11-17" })], TODAY);
  assert.equal(errors.length, 1);
  assert.match(errors[0], /просрочено/);
  assert.match(errors[0], /GHSA-aaaa-bbbb-cccc/);
});

test("запись без причины или с битой датой не проходит", () => {
  assert.match(validateEntries([entry({ reason: " " })], TODAY)[0], /reason/);
  assert.match(validateEntries([entry({ review_by: "01.01.2027" })], TODAY)[0], /не дата/);
});

test("повтор id и не-массив — ошибки, а не молчание", () => {
  assert.match(validateEntries([entry(), entry()], TODAY)[0], /повторяется/);
  assert.match(validateEntries({}, TODAY)[0], /массив/);
});

test("parseDate принимает только YYYY-MM-DD", () => {
  assert.ok(parseDate("2026-11-18"));
  assert.equal(parseDate("2026-13-40"), null);
  assert.equal(parseDate("18.11.2026"), null);
  assert.equal(parseDate(undefined), null);
});

test("toOsvToml отдаёт id и ignoreUntil — единственные поля, которые понимает osv-scanner", () => {
  const toml = toOsvToml([entry()]);
  assert.match(toml, /\[\[IgnoredVulns\]\]/);
  assert.match(toml, /id = "GHSA-aaaa-bbbb-cccc"/);
  assert.match(toml, /ignoreUntil = 2027-01-01/);
  assert.doesNotMatch(toml, /reason/);
});
