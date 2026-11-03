/**
 * Пробник #354: страж обязан краснеть ровно тогда, когда git собирается писать
 * не в то дерево, и только тогда.
 *
 * Реальное дерево не трогаем: проверяем тот же скрипт на временных git-репозиториях,
 * подсовывая KTM_WORKTREE и mixed-окружение (GIT_DIR одного дерева при рабочем
 * каталоге другого). Это и есть критерий (в) — «подложенный чужой путь красит
 * стража, своё дерево проходит».
 *
 * Запуск: npm run test:scripts.
 */

"use strict";

const test = require("node:test");
const assert = require("node:assert/strict");
const { spawnSync } = require("node:child_process");
const { mkdtempSync, rmSync, writeFileSync } = require("node:fs");
const { tmpdir } = require("node:os");
const { join } = require("node:path");

const GUARD = join(__dirname, "guard-tree.mjs");

function scratchRepo() {
  const root = mkdtempSync(join(tmpdir(), "guard-probe-"));
  const repo = join(root, "repo");
  spawnSync("git", ["init", "-q", repo], { encoding: "utf8" });
  writeFileSync(join(repo, "tracked.txt"), "ok\n");
  spawnSync("git", ["-C", repo, "add", "tracked.txt"], { encoding: "utf8" });
  spawnSync("git", ["-C", repo, "-c", "user.email=t@t", "-c", "user.name=t", "commit", "-qm", "probe"], {
    encoding: "utf8",
  });
  return { root, repo };
}

function runGuard(cwd, env) {
  const r = spawnSync(process.execPath, [GUARD, "--json"], {
    cwd,
    encoding: "utf8",
    env: { ...process.env, ...env },
  });
  let json = null;
  try {
    json = JSON.parse(r.stdout);
  } catch {
    /* красные ветки печатают в stderr, stdout пуст — это тоже исход */
  }
  return { code: r.status, out: r.stdout, err: r.stderr, json };
}

test("KTM_WORKTREE не задан — явный no-op с текстом, а не молчаливый успех", () => {
  const { root, repo } = scratchRepo();
  try {
    const env = { ...process.env };
    delete env.KTM_WORKTREE;
    const r = spawnSync(process.execPath, [GUARD], { cwd: repo, encoding: "utf8", env });
    assert.equal(r.status, 0, `no-op обязан выйти нулём: ${r.stderr}`);
    assert.match(`${r.stdout}${r.stderr}`, /KTM_WORKTREE не задан/);
  } finally {
    rmSync(root, { recursive: true, force: true });
  }
});

test("своё дерево проходит, чужое — красное с именами обоих", () => {
  const mine = scratchRepo();
  const foreign = scratchRepo();
  try {
    const good = runGuard(mine.repo, { KTM_WORKTREE: mine.repo });
    assert.equal(good.code, 0, `своё дерево не должно краснеть: ${good.out}${good.err}`);
    assert.equal(good.json.verdict, "GO");

    const bad = runGuard(mine.repo, { KTM_WORKTREE: foreign.repo });
    assert.equal(bad.code, 1, "чужое дерево обязано покраснеть");
    assert.equal(bad.json.verdict, "NO-GO");
    assert.match(JSON.stringify(bad.json.problems), /не совпадает с объявленным/);
  } finally {
    rmSync(mine.root, { recursive: true, force: true });
    rmSync(foreign.root, { recursive: true, force: true });
  }
});

test("правильный рабочий каталог и чужой GIT_DIR — красное: HEAD писался бы не туда", () => {
  const mine = scratchRepo();
  const foreign = scratchRepo();
  try {
    const r = runGuard(mine.repo, {
      KTM_WORKTREE: mine.repo,
      GIT_DIR: join(foreign.repo, ".git"),
      GIT_WORK_TREE: mine.repo,
    });
    assert.equal(r.code, 1, `mixed-окружение обязано покраснеть: ${r.out}`);
    assert.match(JSON.stringify(r.json.problems), /правит не то дерево|не читается/);
  } finally {
    rmSync(mine.root, { recursive: true, force: true });
    rmSync(foreign.root, { recursive: true, force: true });
  }
});

test("несуществующий KTM_WORKTREE — красное сообщение, а не GO", () => {
  const { root, repo } = scratchRepo();
  try {
    const r = runGuard(repo, { KTM_WORKTREE: join(root, "нет-такого") });
    assert.equal(r.code, 1);
    assert.match(r.err, /такого каталога нет/);
  } finally {
    rmSync(root, { recursive: true, force: true });
  }
});
