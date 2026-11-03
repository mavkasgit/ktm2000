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

/**
 * Хуки (lefthook) экспортируют GIT_DIR/GIT_WORK_TREE на реальное дерево, и
 * унаследованное окружение уводит `git init/add/commit` временного репозитория
 * в чужой `.git` — ровно тот баг, который тест должен ловить, а не провоцировать.
 * Поэтому каждый запуск получает чистое от GIT_* окружение; тест сам решает,
 * какой GIT_DIR подложить.
 */
function cleanGitEnv(extra = {}) {
  const env = { ...process.env };
  for (const key of Object.keys(env)) {
    if (key.startsWith("GIT_")) delete env[key];
  }
  return { ...env, ...extra };
}

function scratchRepo(message = "probe") {
  const root = mkdtempSync(join(tmpdir(), "guard-probe-"));
  const repo = join(root, "repo");
  spawnSync("git", ["init", "-q", repo], { encoding: "utf8", env: cleanGitEnv() });
  writeFileSync(join(repo, "tracked.txt"), "ok\n");
  spawnSync("git", ["-C", repo, "add", "tracked.txt"], { encoding: "utf8", env: cleanGitEnv() });
  spawnSync(
    "git",
    ["-C", repo, "-c", "user.email=t@t", "-c", "user.name=t", "commit", "-qm", message],
    { encoding: "utf8", env: cleanGitEnv() },
  );
  return { root, repo };
}

function runGuard(cwd, env) {
  const r = spawnSync(process.execPath, [GUARD, "--json"], {
    cwd,
    encoding: "utf8",
    env: cleanGitEnv(env),
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
    const env = cleanGitEnv();
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

test("GIT_DIR из-под хука не уводит пробник в чужое дерево (регрессия core.bare)", () => {
  const victim = scratchRepo("base");
  const saved = { GIT_DIR: process.env.GIT_DIR, GIT_WORK_TREE: process.env.GIT_WORK_TREE };
  process.env.GIT_DIR = join(victim.repo, ".git");
  delete process.env.GIT_WORK_TREE;
  let probe = null;
  try {
    probe = scratchRepo("probe");
    const victimLog = spawnSync("git", ["-C", victim.repo, "log", "--format=%s"], {
      encoding: "utf8",
      env: cleanGitEnv(),
    });
    assert.deepEqual(
      victimLog.stdout.trim().split("\n"),
      ["base"],
      `чужое дерево получило коммит от пробника: ${victimLog.stdout}`,
    );
    const probeLog = spawnSync("git", ["-C", probe.repo, "log", "--format=%s"], {
      encoding: "utf8",
      env: cleanGitEnv(),
    });
    assert.deepEqual(probeLog.stdout.trim().split("\n"), ["probe"], "свой репозиторий обязан получить свой коммит");
  } finally {
    if (saved.GIT_DIR === undefined) delete process.env.GIT_DIR;
    else process.env.GIT_DIR = saved.GIT_DIR;
    if (saved.GIT_WORK_TREE === undefined) delete process.env.GIT_WORK_TREE;
    else process.env.GIT_WORK_TREE = saved.GIT_WORK_TREE;
    if (probe) rmSync(probe.root, { recursive: true, force: true });
    rmSync(victim.root, { recursive: true, force: true });
  }
});
