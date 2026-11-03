#!/usr/bin/env node
// Страж чужого дерева: git-действие не должно уйти за пределы своего worktree (#354).
//
// Инциденты, из-за которых он появился (PLAYBOOK §10.2, «КУДА ПИСАТЬ»): команда
// `git symbolic-ref HEAD` без `-C` переключила HEAD основного дерева на ветку
// среза, а три правки за ночь легли в чужое дерево. Текстовое правило таких
// случаев не удерживает — нужен механизм, который спрашивает у git, где он
// собирается писать, а не у агента, где тот думает, что работает.
//
// Что проверяется:
//   1. `git rev-parse --show-toplevel` совпадает с объявленным KTM_WORKTREE;
//   2. ref-files (HEAD, index), которые git реально использует, лежат в .git
//      этого дерева, а не основного: linked worktree хранит собственные HEAD и
//      индекс в `<общий>/.git/worktrees/<id>/`, и если из окружения приехал
//      чужой GIT_DIR — команда правит не ту ветку;
//   3. ни одна staged-строка не указывает за пределы дерева (git такие записи
//      создавать не даёт, это страховка от чужого/будущего индекса).
//
// KTM_WORKTREE не задан — явный no-op с текстом, а не молчаливый успех: молча
// «прошёл» неотличим от «проверил и всё хорошо».

import { spawnSync } from "node:child_process";
import { existsSync, realpathSync } from "node:fs";
import { dirname, isAbsolute, resolve } from "node:path";
import { fileURLToPath } from "node:url";

const SELF_ROOT = dirname(dirname(fileURLToPath(import.meta.url)));
const args = process.argv.slice(2);
const jsonOut = args.includes("--json");
const unknown = args.filter((a) => a !== "--json");
if (unknown.length) {
  console.error(`guard-tree: неизвестный аргумент ${unknown.join(" ")} (есть --json)`);
  process.exit(2);
}

/**
 * На Windows один и тот же каталог приходит то длинным именем, то 8.3-вариантом
 * (`C:\Users\LOGOPR~1` против `C:\Users\LogoPrint`), и сравнение строк выло бы
 * ложным красным. realpathSync приводит обе формы к фактическому имени; для
 * несуществующего пути (его и проверяем, что нет) остаётся resolve.
 */
function abs(p) {
  let out = resolve(p);
  try {
    out = realpathSync.native ? realpathSync.native(out) : realpathSync(out);
  } catch {
    /* пути нет — сравниваем как есть */
  }
  return out.replaceAll("\\", "/").replace(/\/+$/, "").toLowerCase();
}

const norm = abs;

function git(...rest) {
  const r = spawnSync("git", rest, { encoding: "utf8" });
  return {
    ok: r.status === 0,
    out: (r.stdout || "").trim(),
    err: (r.stderr || "").trim(),
    code: r.status,
  };
}

/**
 * Тот же git без переменных окружения, которые переводят его в чужое дерево.
 * Нужно для «эталонного» ответа: `git -C <дерево>` с оставшимся в окружении
 * GIT_DIR отвечает не про дерево, а про подвешенный каталог, и сравнение двух
 * ответов становилось тождественным.
 */
function gitClean(...rest) {
  const env = { ...process.env };
  for (const leak of ["GIT_DIR", "GIT_WORK_TREE", "GIT_INDEX_FILE", "GIT_COMMON_DIR"]) delete env[leak];
  const r = spawnSync("git", rest, { encoding: "utf8", env });
  return { ok: r.status === 0, out: (r.stdout || "").trim(), err: (r.stderr || "").trim() };
}

/** Абсолютный путь ref-файла, который git реально читает/пишет. */
function gitPath(key) {
  const rel = git("rev-parse", "--git-path", key);
  if (!rel.ok || !rel.out) return null;
  const root = git("rev-parse", "--show-toplevel").out || SELF_ROOT;
  return isAbsolute(rel.out) ? resolve(rel.out) : resolve(root, rel.out);
}

/**
 * Деревом считаем то, которое git вернул по `--show-toplevel`; общий каталог
 * `.git` — по `--git-common-dir` (у linked worktree он указывает на основное
 * дерево, и именно туда уходит команда без `-C`).
 */
function inspect() {
  const toplevel = git("rev-parse", "--show-toplevel");
  const common = git("rev-parse", "--path-format=absolute", "--git-common-dir");
  let commonDir = null;
  if (common.ok && common.out) {
    // Старый git не знает `--path-format=absolute`: тогда путь относительный к
    // корню дерева, и его надо достроить самим.
    commonDir = isAbsolute(common.out) ? resolve(common.out) : resolve(git("rev-parse", "--show-toplevel").out || SELF_ROOT, common.out);
  }
  const head = git("symbolic-ref", "HEAD");
  return {
    toplevel: toplevel.ok ? resolve(toplevel.out) : null,
    commonDir,
    branch: head.ok ? head.out.replace(/^refs\/heads\//, "") : null,
    headFile: gitPath("HEAD"),
    indexFile: gitPath("index"),
  };
}

function stagedPaths() {
  const r = git("diff", "--cached", "--name-only", "-z");
  if (!r.ok) return { ok: false, paths: [] };
  return { ok: true, paths: (r.stdout || "").split("\0").filter(Boolean) };
}

/** Path из индекса обязан оставаться внутри корня дерева. */
function escapes(rootAbs, relPath) {
  const abs = resolve(rootAbs, relPath);
  const r = norm(rootAbs);
  const a = norm(abs);
  return a !== r && !a.startsWith(`${r}/`);
}

const declared = process.env.KTM_WORKTREE;
if (!declared) {
  const message =
    "KTM_WORKTREE не задан — страж ничего не сверяет (это no-op, а не «всё хорошо»). " +
    "Для агента в worktree: export KTM_WORKTREE=$(git rev-parse --show-toplevel) своего дерева.";
  if (jsonOut) {
    console.log(JSON.stringify({ verdict: "no-op", reason: message }, null, 2));
  } else {
    console.log(`guard-tree: ${message}`);
  }
  process.exit(0);
}

if (!existsSync(declared)) {
  console.error(`guard-tree: KTM_WORKTREE=${declared} — такого каталога нет`);
  process.exit(1);
}

const where = inspect();
const problems = [];
const facts = { declared: resolve(declared), ...where };

if (!where.toplevel) {
  problems.push("git rev-parse --show-toplevel не ответил — вне git-дерева страж бессилен");
} else if (norm(where.toplevel) !== norm(resolve(declared))) {
  problems.push(
    `дерево, на которое указывает git (${where.toplevel}), не совпадает с объявленным (${resolve(declared)})`,
  );
}

// ref-файлы: HEAD и индекс пишут в `<absolute-git-dir>`. Сравниваем тот, который
// git использует сейчас, с тем, что зарегистрирован у объявленного дерева:
// mixed-окружение (правильный cwd + чужой GIT_DIR) даёт совпадающий toplevel и
// уводит запись в основное дерево — ровно инцидент с переключённой веткой.
const currentGitDir = git("rev-parse", "--absolute-git-dir");
const expectedGitDir = gitClean("-C", resolve(declared), "rev-parse", "--absolute-git-dir");
facts.currentGitDir = currentGitDir.ok ? resolve(currentGitDir.out) : null;
facts.expectedGitDir = expectedGitDir.ok ? resolve(expectedGitDir.out) : null;
if (!currentGitDir.ok || !expectedGitDir.ok) {
  problems.push(
    `git-dir не читается (сейчас: ${currentGitDir.out || currentGitDir.err || "нет"}, ` +
      `у объявленного дерева: ${expectedGitDir.out || expectedGitDir.err || "нет"})`,
  );
} else if (norm(currentGitDir.out) !== norm(expectedGitDir.out)) {
  problems.push(
    `HEAD и индекс берутся из ${resolve(currentGitDir.out)}, а у объявленного дерева ${resolve(expectedGitDir.out)} — команда правит не то дерево`,
  );
}

const staged = stagedPaths();
if (!staged.ok) {
  problems.push("git diff --cached не выполнился — пропущенные staged-файлы не видны");
} else {
  const root = where.toplevel || resolve(declared);
  const foreign = staged.paths.filter((p) => escapes(root, p));
  if (foreign.length) {
    problems.push(`staged-пути за пределами дерева: ${foreign.join(", ")}`);
  }
  facts.staged = staged.paths.length;
}

const verdict = problems.length ? "NO-GO" : "GO";
if (jsonOut) {
  console.log(JSON.stringify({ verdict, problems, facts }, null, 2));
} else if (problems.length) {
  console.error(`guard-tree: NO-GO — действия git уходят из своего дерева:`);
  for (const p of problems) console.error(`  ✗ ${p}`);
  console.error(
    `  ветка того дерева: ${where.branch ?? "не читается"}; общий .git: ${where.commonDir ?? "не читается"}`,
  );
} else {
  console.log(
    `guard-tree: GO — дерево ${where.toplevel}, ветка ${where.branch ?? "detached"}, staged ${facts.staged ?? 0}`,
  );
}

process.exitCode = problems.length ? 1 : 0;
