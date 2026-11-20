#!/usr/bin/env node
// Скоуп локального pre-push гейта.
//
// Считает, какие зоны затронуты в `git diff <base>...HEAD`, и отдаёт список
// шагов `npm run gate -- --only=...`. Работает одинаково для main, feature-ветки
// и worktree: база — `origin/main`, если её нет — локальная `main`.
//
// Fail-safe: неизвестный путь, отсутствие базы или недоступный diff означают
// полный `npm run gate`, а не «наверное, пронесёт».

import { execFileSync } from "node:child_process";
import { pathToFileURL } from "node:url";

const DOCS = /^(?:docs\/|.*\.md$)/i;
const BACKEND = /^backend\//;
const FRONTEND = /^frontend\//;

/** Шаги для docs-only правки: ~2 с. */
export const DOCS_STEPS = ["docs-links", "docs-lint", "adr-index", "ci-lint"];

/** Шаги для backend: миграционные быстрые проверки + тесты. */
export const BACKEND_STEPS = [
  "pins",
  "ruff",
  "backend-tests",
  "backend-test-count",
  "test-hygiene",
  "labels-check",
  "seeds-validate",
  "profile-settings-manifest",
];

/** Шаги для frontend: типы, линтер, unit, счётчик, сборка и рэтчеты. */
export const FRONTEND_STEPS = [
  "pins",
  "frontend-types",
  "frontend-types-e2e",
  "frontend-lint",
  "frontend-unit",
  "frontend-test-count",
  "frontend-build",
  "reactuse-diff",
  "modern-web",
  "dev-deps",
];

/** Пути из git всегда posix; нормализуем и значение из env/тестов. */
export function normalizePath(value) {
  return String(value).trim().replaceAll("\\", "/");
}

function isKnown(file) {
  return DOCS.test(file) || BACKEND.test(file) || FRONTEND.test(file);
}

/**
 * Чистая функция: список файлов -> `docs` | `backend` | `frontend` | `full`.
 *
 * - всё документация -> docs;
 * - только backend или только frontend -> соответствующая зона;
 * - обе зоны, неизвестный путь (workflow, scripts, lock-файлы, infra) -> full.
 */
export function detectScope(files) {
  const changed = files.map(normalizePath).filter(Boolean);
  if (changed.length === 0) return "full";
  if (changed.some((file) => !isKnown(file))) return "full";
  if (changed.every((file) => DOCS.test(file))) return "docs";

  const backend = changed.some((file) => BACKEND.test(file));
  const frontend = changed.some((file) => FRONTEND.test(file));
  if (backend && frontend) return "full";
  if (backend) return "backend";
  if (frontend) return "frontend";
  return "docs";
}

/**
 * План прогона: `steps === null` означает «полный `npm run gate`».
 * Документация, затронутая вместе с кодом, добавляет свои шаги к шагам зоны.
 */
export function planFor(files) {
  const changed = files.map(normalizePath).filter(Boolean);
  const scope = detectScope(changed);
  if (scope === "full") return { scope, steps: null };

  const steps = new Set(scope === "docs" ? DOCS_STEPS : scope === "backend" ? BACKEND_STEPS : FRONTEND_STEPS);
  if (scope !== "docs" && changed.some((file) => DOCS.test(file))) {
    for (const step of DOCS_STEPS) steps.add(step);
  }

  return { scope, steps: [...steps] };
}

function git(args, cwd, exec) {
  return exec("git", args, { cwd, encoding: "utf8" });
}

/** Первая существующая база: origin/main, затем main. null -> полный гейт. */
export function resolveBase({ cwd = process.cwd(), exec = execFileSync } = {}) {
  for (const ref of ["origin/main", "main"]) {
    try {
      git(["rev-parse", "--verify", "--quiet", `${ref}^{commit}`], cwd, exec);
      return ref;
    } catch {
      // пробуем следующую
    }
  }
  return null;
}

/** Список файлов или null, если diff не удался (наверху станет full). */
export function listChangedFiles(
  { base, head = "HEAD", cwd = process.cwd(), exec = execFileSync },
) {
  try {
    const output = git(
      ["diff", "--name-only", "--no-renames", `${base}...${head}`],
      cwd,
      exec,
    );
    return String(output)
      .split(/\r?\n/)
      .map(normalizePath)
      .filter(Boolean);
  } catch {
    return null;
  }
}

/** Полный расчёт: база -> файлы -> план. */
export function resolvePlan({
  cwd = process.cwd(),
  exec = execFileSync,
  base = null,
  head = "HEAD",
  files = null,
} = {}) {
  if (files !== null) {
    return { ...planFor(files), files: files.map(normalizePath).filter(Boolean), base: null };
  }

  const resolvedBase = base || resolveBase({ cwd, exec });
  if (!resolvedBase) {
    return { scope: "full", steps: null, files: [], base: null };
  }

  const changed = listChangedFiles({ base: resolvedBase, head, cwd, exec });
  if (changed === null) {
    return { scope: "full", steps: null, files: [], base: resolvedBase };
  }

  return { ...planFor(changed), files: changed, base: resolvedBase };
}

function parseFileList(value) {
  return String(value)
    .split(",")
    .map(normalizePath)
    .filter(Boolean);
}

function main() {
  const args = process.argv.slice(2);
  const filesArg = args.find((arg) => arg.startsWith("--files="));
  const baseArg = args.find((arg) => arg.startsWith("--base="));
  const json = args.includes("--json");

  const plan = resolvePlan({
    files: filesArg ? parseFileList(filesArg.slice("--files=".length)) : null,
    base: baseArg ? baseArg.slice("--base=".length) : null,
  });

  if (json) {
    console.log(JSON.stringify(plan, null, 2));
    return;
  }

  console.log(`scope: ${plan.scope}`);
  console.log(`base: ${plan.base ?? "—"}`);
  console.log(`files: ${plan.files.length}`);
  console.log(`steps: ${plan.steps === null ? "полный npm run gate" : plan.steps.join(",")}`);
}

if (process.argv[1] && import.meta.url === pathToFileURL(process.argv[1]).href) {
  main();
}
