/**
 * Пробник #360: doctor обязан краснеть ровно по той строке, которую сломали.
 *
 * Реальное дерево не трогаем — проверяем тот же скрипт на временном git-репозитории
 * через `--root=`. Это исполняет критерий (в) «временно переименованный .env.test ⇒
 * NO-GO именно по этой строке», но без риска для чужого WIP и без следа в дереве.
 *
 * Запуск: npm run test:scripts.
 */

"use strict";

const test = require("node:test");
const assert = require("node:assert/strict");
const { spawnSync } = require("node:child_process");
const { mkdtempSync, writeFileSync, rmSync } = require("node:fs");
const { tmpdir } = require("node:os");
const { join } = require("node:path");

const DOCTOR = join(__dirname, "doctor.mjs");

/**
 * В чистом scratch-репозитории красных строк больше одной (нет коммитов, нет
 * node_modules) — поэтому verdict всегда NO-GO и код выхода 1. Значимая часть
 * пробника — какие именно строки красные: проверяем только их.
 */
function run(root) {
  const r = spawnSync(process.execPath, [DOCTOR, `--root=${root}`, "--json"], {
    encoding: "utf8",
  });
  assert.equal(r.status, 1, `доктор обязан покраснеть, а он вернул ${r.status}: ${r.stdout}${r.stderr}`);
  return JSON.parse(r.stdout);
}

/** Свежий worktree-подобное дерево: env-файлов нет ни одного. */
function scratchRoot(envFiles) {
  const root = mkdtempSync(join(tmpdir(), "doctor-probe-"));
  spawnSync("git", ["init", "-q", root], { encoding: "utf8" });
  for (const f of envFiles) writeFileSync(join(root, f), "PROBE=1\n");
  return root;
}

test("нет .env.test — красной строкой именно он, остальные env-файлы не при чём", () => {
  const root = scratchRoot([".env.dev", ".env.e2e"]);
  try {
    const out = run(root);
    const envBlockers = out.blockers.filter((b) => b.startsWith("env "));
    assert.deepEqual(envBlockers, ["env .env.test: .env.test нет — в новом worktree их надо копировать из основного дерева"]);
    assert.equal(out.verdict, "NO-GO");
  } finally {
    rmSync(root, { recursive: true, force: true });
  }
});

test("все три env-файла на месте — ни одной красной строки про env", () => {
  const root = scratchRoot([".env.dev", ".env.test", ".env.e2e"]);
  try {
    const out = run(root);
    assert.deepEqual(out.blockers.filter((b) => b.startsWith("env ")), []);
  } finally {
    rmSync(root, { recursive: true, force: true });
  }
});

test("неизвестный аргумент — красное usage и код 2, а не молчаливый GO", () => {
  const r = spawnSync(process.execPath, [DOCTOR, "--all"], { encoding: "utf8" });
  assert.equal(r.status, 2);
  assert.match(r.stderr, /неизвестный аргумент/);
});
