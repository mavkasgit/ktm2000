/**
 * Пробник T-384: гейт берёт python из `backend/.venv` проекта, а не первый
 * `python` из PATH.
 *
 * Проверяется чистый резолвер (`scripts/python-core.js`): существование venv
 * подставляется, поэтому тест не зависит от машины и от того, установлен ли
 * venv в текущем дереве. Настоящая подмена PATH — ручная приёмка в PR: гейт с
 * чужим `python` первым в PATH обязан напечатать версию из `backend/.venv`.
 *
 * Запуск: npm run test:scripts.
 */

"use strict";

const test = require("node:test");
const assert = require("node:assert/strict");
const { join } = require("node:path");

const { resolvePython, venvPython } = require("./python-core.js");

const ROOT = join("C:", "repo");

test("venv проекта есть — берётся он, PATH не спрашивается", () => {
  const out = resolvePython({ root: ROOT, env: {}, platform: "win32", exists: () => true });
  assert.equal(out.source, "venv");
  assert.equal(out.exe, join(ROOT, "backend", ".venv", "Scripts", "python.exe"));
});

test("POSIX-раскладка venv — bin/python (иное дерево, тот же резолвер)", () => {
  assert.equal(venvPython("/srv/ktm", "linux"), join("/srv/ktm", "backend", ".venv", "bin", "python"));
  const out = resolvePython({ root: "/srv/ktm", env: {}, platform: "linux", exists: () => true });
  assert.equal(out.exe, join("/srv/ktm", "backend", ".venv", "bin", "python"));
});

test("venv нет — запасной путь python из PATH, и это названо в источнике", () => {
  const out = resolvePython({ root: ROOT, env: {}, platform: "win32", exists: () => false });
  assert.equal(out.source, "path");
  assert.equal(out.exe, "python");
});

test("KTM_PYTHON — осознанный override, сильнее venv", () => {
  const out = resolvePython({
    root: ROOT,
    env: { KTM_PYTHON: "C:/other/python.exe" },
    platform: "win32",
    exists: () => true,
  });
  assert.equal(out.source, "env");
  assert.equal(out.exe, "C:/other/python.exe");
});

test("TEST_PYTHON — тот же override для дерева без своего venv", () => {
  const out = resolvePython({
    root: ROOT,
    env: { TEST_PYTHON: "C:/main/backend/.venv/Scripts/python.exe" },
    platform: "win32",
    exists: () => false,
  });
  assert.equal(out.source, "env");
  assert.equal(out.exe, "C:/main/backend/.venv/Scripts/python.exe");
});

test("пустая строка override не считается выбором — работает venv", () => {
  const out = resolvePython({
    root: ROOT,
    env: { KTM_PYTHON: "", TEST_PYTHON: "  " },
    platform: "win32",
    exists: () => true,
  });
  assert.equal(out.source, "venv");
});

test("пробелы вокруг override срезаются: путь с хвостом не должен ломать запуск", () => {
  const out = resolvePython({
    root: ROOT,
    env: { KTM_PYTHON: "  C:/other/python.exe  " },
    platform: "win32",
    exists: () => false,
  });
  assert.equal(out.exe, "C:/other/python.exe");
});
