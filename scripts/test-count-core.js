// scripts/test-count-core.js
"use strict";

/**
 * Разбор вывода сборщиков тестов и сверка с рэтчетом (#358).
 *
 * Рэтчет, а не статистика: число тестов имеет право только расти. Уменьшение
 * означает, что тесты удалили или спрятали (skip, маркер, переименованный файл),
 * и его видно по конкретным файлам, а не по смутному «стало меньше».
 *
 * Парсеры нарочно требовательны: нераспознанная строка — красный результат, а не
 * пропущенная. Молча посчитать «то, что удалось разобрать» означало бы пережить
 * смену формата сборщика ровно тем способом, который рэтчет обязан ловить.
 */

const PYTEST_ID = /^(.*\.py)::(.+)$/;
const PYTEST_SUMMARY = /^(\d+) tests? collected in [\d.]+s$/;
const PYTEST_BOILERPLATE = [/^=+ .* =+$/, /^\d+ (?:warnings?|errors?) in [\d.]+s$/];
const VITEST_ID = /^(.*\.(?:test|spec)\.(?:[cm]?js|tsx?)) > .+$/;
const path = require("node:path");

function byFile(ids) {
  const counts = {};
  for (const file of ids) counts[file] = (counts[file] || 0) + 1;
  return counts;
}

function ignorable(line) {
  return PYTEST_BOILERPLATE.some((re) => re.test(line));
}

/**
 * Вывод `pytest --collect-only -q`: построчные node-id плюс итоговая строка
 * «N tests collected in X». Итог сверяется с числом разобранных id — расходится
 * значит вывод обрезан или сборщик сказал что-то, чего парсер не знает.
 */
function parsePytestCollect(raw) {
  const files = [];
  const anomalies = [];
  let total = null;
  for (const line of raw.split(/\r?\n/)) {
    const t = line.trim();
    if (!t) continue;
    const id = PYTEST_ID.exec(t);
    if (id) {
      files.push(id[1]);
      continue;
    }
    const summary = PYTEST_SUMMARY.exec(t);
    if (summary) {
      total = Number(summary[1]);
      continue;
    }
    if (ignorable(t)) continue;
    anomalies.push(t);
  }
  if (total === null) {
    return { ok: false, reason: "нет итоговой строки «N tests collected in …»", anomalies: anomalies.slice(0, 5) };
  }
  if (anomalies.length) {
    return { ok: false, reason: `вывод pytest не разобран (${anomalies.length} строк)`, anomalies: anomalies.slice(0, 5) };
  }
  if (files.length !== total) {
    return { ok: false, reason: `итог говорит ${total}, id-строк ${files.length}`, anomalies: [] };
  }
  return { ok: true, total, by_file: byFile(files) };
}

/**
 * Вывод `vitest list`: одна строка на тест — `<файл> > <сьют> > <заголовок>`.
 * Итогового числа у `list` нет, поэтому количество = число разобранных строк.
 */
function parseVitestList(raw) {
  const files = [];
  const anomalies = [];
  for (const line of raw.split(/\r?\n/)) {
    const t = line.trim();
    if (!t) continue;
    const id = VITEST_ID.exec(t);
    if (id) {
      files.push(id[1]);
      continue;
    }
    anomalies.push(t);
  }
  if (anomalies.length) {
    return { ok: false, reason: `вывод vitest не разобран (${anomalies.length} строк)`, anomalies: anomalies.slice(0, 5) };
  }
  if (!files.length) {
    return { ok: false, reason: "vitest не выдал ни одного теста — это не «ноль тестов», а сломанный сбор", anomalies: [] };
  }
  return { ok: true, total: files.length, by_file: byFile(files) };
}

/**
 * Отчёт `vitest run --reporter=json`.
 *
 * `vitest list` в v5 печатает `it.each` одной строкой с неразвёрнутым `%s`
 * и склеивает одинаковые заголовки, поэтому число тестов по файлу занижается
 * (в `taskStatus.test.ts` 34 вместо 59). JSON-репорт запуска содержит
 * `assertionResults` на каждый развёрнутый кейс — по нему счётчик совпадает
 * с фактическим прогоном. Цена — тесты реально выполняются, зато рэтчет
 * видит каждый тест, а не первый из таблицы.
 */
function parseVitestJson(raw, cwd = process.cwd()) {
  let report;
  try {
    report = JSON.parse(raw);
  } catch (error) {
    return { ok: false, reason: `JSON vitest не разобран: ${error.message}`, anomalies: [] };
  }
  if (!report || !Array.isArray(report.testResults) || typeof report.numTotalTests !== "number") {
    return { ok: false, reason: "JSON vitest без testResults/numTotalTests — формат не тот", anomalies: [] };
  }
  const files = [];
  for (const suite of report.testResults) {
    const rel = path.relative(cwd, suite.name).split(path.sep).join("/");
    for (const _ of suite.assertionResults || []) files.push(rel);
  }
  if (files.length !== report.numTotalTests) {
    return {
      ok: false,
      reason: `итог говорит ${report.numTotalTests}, assertionResults ${files.length}`,
      anomalies: [],
    };
  }
  if (!files.length) {
    return { ok: false, reason: "vitest не выдал ни одного теста — это не «ноль тестов», а сломанный сбор", anomalies: [] };
  }
  return { ok: true, total: files.length, by_file: byFile(files) };
}

/** Только уменьшения: файл стал короче или исчез совсем. Рост — не находка. */
function findReductions(baseline, current) {
  const lost = [];
  for (const [file, before] of Object.entries(baseline)) {
    const after = current[file] === undefined ? 0 : current[file];
    if (after < before) lost.push({ file, before, after });
  }
  return lost.sort((a, b) => b.before - b.after - (a.before - a.after) || a.file.localeCompare(b.file));
}

function formatReductions(lost) {
  return lost.map((l) => `  ${l.file}: ${l.before} → ${l.after} (−${l.before - l.after})`);
}

/**
 * Сверка собранного с записанным. Итог и пофайловый дифф — две половины одного
 * утверждения «собрано не меньше записанного»: ровный итог при пропавшем файле
 * возможен (тесты переехали в другой файл), поэтому красным считается и то,
 * и другое.
 */
function evaluateStored(stored, current) {
  const reductions = findReductions(stored.by_file, current.by_file);
  const dropped = current.total < stored.total;
  const reason = dropped
    ? `собрано меньше минимума: ${stored.total} → ${current.total}`
    : reductions.length
      ? "итог не изменился, но тесты пропали в конкретных файлах"
      : "";
  return {
    ok: !dropped && reductions.length === 0,
    reason,
    total: current.total,
    baseline_total: stored.total,
    files: Object.keys(current.by_file).length,
    reductions,
  };
}

module.exports = { parsePytestCollect, parseVitestList, parseVitestJson, findReductions, formatReductions, evaluateStored };
