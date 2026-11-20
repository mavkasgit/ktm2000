"use strict";
// Тесты локального скоупа pre-push гейта (scripts/ci/changed-scopes.mjs).
// Запускаются шагом `scripts-tests`: `npm run test:scripts`.

const { test } = require("node:test");
const assert = require("node:assert/strict");

const load = () => import("./changed-scopes.mjs");

test("normalizePath: приводит Windows-разделители и пробелы", async () => {
  const { normalizePath } = await load();
  assert.equal(normalizePath("backend\\app\\main.py\r\n"), "backend/app/main.py");
});

test("detectScope: только документация -> docs", async () => {
  const { detectScope } = await load();
  assert.equal(detectScope(["docs/quality/gates.md", "README.md"]), "docs");
});

test("detectScope: backend -> backend", async () => {
  const { detectScope } = await load();
  assert.equal(detectScope(["backend/app/main.py", "backend/tests/test_api.py"]), "backend");
});

test("detectScope: frontend -> frontend", async () => {
  const { detectScope } = await load();
  assert.equal(detectScope(["frontend/src/App.tsx"]), "frontend");
});

test("detectScope: backend + frontend -> full", async () => {
  const { detectScope } = await load();
  assert.equal(detectScope(["backend/app/main.py", "frontend/src/App.tsx"]), "full");
});

test("detectScope: docs + backend -> backend (docs не отменяет код)", async () => {
  const { detectScope } = await load();
  assert.equal(detectScope(["docs/quality/gates.md", "backend/app/main.py"]), "backend");
});

test("detectScope: .md внутри кода считается документацией", async () => {
  const { detectScope } = await load();
  assert.equal(detectScope(["backend/README.md", "frontend/README.md"]), "docs");
});

test("detectScope: workflow/config/неизвестный путь -> full", async () => {
  const { detectScope } = await load();
  for (const file of [
    ".github/workflows/ci-lint.yml",
    "scripts/ci/changed-scopes.mjs",
    "package-lock.json",
    "mise.toml",
    "infra/compose/docker-compose.dev.yml",
  ]) {
    assert.equal(detectScope([file]), "full", file);
  }
});

test("detectScope: пустой список -> full (fail-safe)", async () => {
  const { detectScope } = await load();
  assert.equal(detectScope([]), "full");
});

test("planFor: docs -> docs-шаги", async () => {
  const { planFor, DOCS_STEPS } = await load();
  assert.deepEqual(planFor(["docs/quality/gates.md"]), {
    scope: "docs",
    steps: DOCS_STEPS,
  });
});

test("planFor: backend -> backend-шаги + docs при смеси", async () => {
  const { planFor, BACKEND_STEPS, DOCS_STEPS } = await load();
  const plan = planFor(["backend/app/main.py", "docs/quality/gates.md"]);
  assert.equal(plan.scope, "backend");
  for (const step of [...BACKEND_STEPS, ...DOCS_STEPS]) {
    assert.ok(plan.steps.includes(step), step);
  }
});

test("planFor: frontend -> frontend-шаги", async () => {
  const { planFor, FRONTEND_STEPS } = await load();
  assert.deepEqual(planFor(["frontend/src/App.tsx"]).steps, FRONTEND_STEPS);
});

test("planFor: full -> steps = null (полный npm run gate)", async () => {
  const { planFor } = await load();
  assert.deepEqual(planFor(["backend/app/main.py", "frontend/src/App.tsx"]), {
    scope: "full",
    steps: null,
  });
});

test("resolvePlan: diff от base -> план", async () => {
  const { resolvePlan } = await load();
  const exec = (command, args) => {
    if (args[0] === "rev-parse") return "abc\n";
    if (args[0] === "diff") return "backend/app/main.py\nbackend/tests/test_api.py\n";
    throw new Error(`unexpected git ${args.join(" ")}`);
  };
  const plan = resolvePlan({ exec, cwd: "C:/repo" });
  assert.equal(plan.scope, "backend");
  assert.equal(plan.base, "origin/main");
  assert.ok(plan.steps.includes("backend-tests"));
});

test("resolvePlan: базы нет -> full", async () => {
  const { resolvePlan } = await load();
  const exec = () => {
    throw new Error("no ref");
  };
  assert.deepEqual(resolvePlan({ exec }), {
    scope: "full",
    steps: null,
    files: [],
    base: null,
  });
});

test("resolvePlan: diff упал -> full (fail-safe)", async () => {
  const { resolvePlan } = await load();
  const exec = (command, args) => {
    if (args[0] === "rev-parse") return "abc\n";
    throw new Error("bad diff");
  };
  const plan = resolvePlan({ exec });
  assert.equal(plan.scope, "full");
  assert.equal(plan.steps, null);
});

test("resolvePlan: явный список файлов минует git", async () => {
  const { resolvePlan } = await load();
  const plan = resolvePlan({ files: ["docs/a.md"], exec: () => {
    throw new Error("git не должен вызываться");
  } });
  assert.equal(plan.scope, "docs");
});
