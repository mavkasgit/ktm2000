/**
 * Тесты трещотки предупреждений (#372).
 *
 * Прогон ESLint подменяется фиктивным `runEslint` — реальный линтер здесь не
 * нужен (он ~40 с на всё дерево), важны именно коды выхода и сообщения
 * гейта. Отдельным блоком проверяется целостность закоммиченного базового
 * файла.
 */
import { afterEach, describe, expect, it } from "vitest";
import fs from "node:fs";
import os from "node:os";
import path from "node:path";
import {
  BASELINE_PATH,
  compare,
  countWarnings,
  main,
  renderReport,
} from "./lint-ratchet.mjs";

const tempDirs = [];

/** @param {Record<string, unknown>} [files] */
function tempTree(files) {
  const dir = fs.mkdtempSync(path.join(os.tmpdir(), "lint-ratchet-"));
  tempDirs.push(dir);
  const baseline = path.join(dir, "eslint-warnings-baseline.json");
  if (files) fs.writeFileSync(baseline, JSON.stringify(files, null, 2), "utf8");
  return { dir, baseline };
}

afterEach(() => {
  while (tempDirs.length) {
    fs.rmSync(tempDirs.pop(), { recursive: true, force: true });
  }
});

/**
 * Фиктивный прогон ESLint: раскладывает числа по файлам как это делает сам
 * ESLint (`--format=json`), чтобы `countWarnings` считал по-настоящему.
 *
 * @param {{warnings?: Record<string, number>, errors?: number, status?: number, raw?: string}} spec
 */
function fakeEslint(spec) {
  const { warnings = {}, errors = 0, status, raw } = spec;
  const results = [];
  let left = errors;
  let index = 0;
  for (const [rule, count] of Object.entries(warnings)) {
    for (let i = 0; i < count; i += 1) {
      results.push({
        filePath: `src/fake/${(index += 1)}.tsx`,
        errorCount: 0,
        warningCount: 1,
        messages: [{ severity: 1, ruleId: rule }],
      });
    }
  }
  if (left > 0) {
    results.push({
      filePath: "src/fake/errors.tsx",
      errorCount: left,
      warningCount: 0,
      messages: Array.from({ length: left }, () => ({
        severity: 2,
        ruleId: "boundaries/dependencies",
      })),
    });
  }
  return {
    status: status ?? (left > 0 ? 1 : 0),
    stdout: raw ?? JSON.stringify(results),
    stderr: "",
  };
}

describe("countWarnings", () => {
  it("суммирует предупреждения и разносит по правилам", () => {
    const counts = countWarnings([
      {
        errorCount: 0,
        warningCount: 2,
        messages: [
          { severity: 1, ruleId: "react-hooks/exhaustive-deps" },
          { severity: 1, ruleId: "react-hooks/exhaustive-deps" },
        ],
      },
      {
        errorCount: 1,
        warningCount: 1,
        messages: [
          { severity: 1, ruleId: "no-console" },
          { severity: 2, ruleId: "boundaries/dependencies" },
        ],
      },
    ]);
    expect(counts).toEqual({
      total: 3,
      errors: 1,
      byRule: { "react-hooks/exhaustive-deps": 2, "no-console": 1 },
    });
  });

  it("предупреждение без правила не теряется", () => {
    const counts = countWarnings([
      {
        errorCount: 0,
        warningCount: 1,
        messages: [{ severity: 1, ruleId: null }],
      },
    ]);
    expect(counts.total).toBe(1);
    expect(counts.byRule["(без правила)"]).toBe(1);
  });
});

describe("compare", () => {
  const baseline = { total: 2, byRule: { "react-hooks/exhaustive-deps": 2 } };

  it("равно потолку — зелёный", () => {
    const diff = compare(baseline, {
      total: 2,
      errors: 0,
      byRule: { "react-hooks/exhaustive-deps": 2 },
    });
    expect(diff.ok).toBe(true);
    expect(diff.problems).toEqual([]);
    expect(diff.improvements).toEqual([]);
  });

  it("плюс одно предупреждение — красный с дельтой в сообщении", () => {
    const diff = compare(baseline, {
      total: 3,
      errors: 0,
      byRule: { "react-hooks/exhaustive-deps": 3 },
    });
    expect(diff.ok).toBe(false);
    expect(diff.problems.join("\n")).toMatch(/react-hooks\/exhaustive-deps: было 2, стало 3 \(\+1\)/);
  });

  it("перераспределение при неизменной сумме — красный", () => {
    // Одно исправили, одно добавили: сумма та же, дефект появился.
    const diff = compare(
      { total: 2, byRule: { "react-hooks/exhaustive-deps": 2 } },
      {
        total: 2,
        errors: 0,
        byRule: { "react-hooks/exhaustive-deps": 1, "no-console": 1 },
      },
    );
    expect(diff.ok).toBe(false);
    expect(diff.problems.join("\n")).toMatch(/no-console: 1 предупреждений при потолке 0/);
  });

  it("меньше потолка — зелёный и подсказка подтянуть", () => {
    const diff = compare(baseline, {
      total: 1,
      errors: 0,
      byRule: { "react-hooks/exhaustive-deps": 1 },
    });
    expect(diff.ok).toBe(true);
    expect(diff.improvements.length).toBeGreaterThan(0);
  });

  it("ошибки красят прогон, даже если предупреждений ровно потолок", () => {
    const diff = compare(baseline, {
      total: 2,
      errors: 1,
      byRule: { "react-hooks/exhaustive-deps": 2 },
    });
    expect(diff.ok).toBe(false);
    expect(diff.problems.join("\n")).toMatch(/ошибок ESLint: 1/);
  });
});

describe("renderReport", () => {
  it("показывает числа текущего замера и потолка", () => {
    const text = renderReport(
      { total: 48, byRule: { "react-hooks/exhaustive-deps": 48 } },
      { total: 48, errors: 0, byRule: { "react-hooks/exhaustive-deps": 48 } },
      { ok: true, problems: [], improvements: [] },
      { files: 529 },
    );
    expect(text).toContain("файлов 529");
    expect(text).toContain("предупреждений 48 (потолок 48)");
    expect(text).toContain("react-hooks/exhaustive-deps: 48 (потолок 48)");
  });
});

describe("main", () => {
  it("ровно потолок -> код 0", async () => {
    const { baseline } = tempTree({ total: 48, byRule: { "react-hooks/exhaustive-deps": 48 } });
    const out = [];
    const code = await main([], {
      baselineFile: baseline,
      runEslint: () => fakeEslint({ warnings: { "react-hooks/exhaustive-deps": 48 } }),
      log: (text) => out.push(text),
    });
    expect(code).toBe(0);
    expect(out.join("\n")).toContain("предупреждений 48 (потолок 48)");
  });

  it("рост на одно предупреждение -> код 1", async () => {
    const { baseline } = tempTree({ total: 48, byRule: { "react-hooks/exhaustive-deps": 48 } });
    const out = [];
    const code = await main([], {
      baselineFile: baseline,
      runEslint: () => fakeEslint({ warnings: { "react-hooks/exhaustive-deps": 49 } }),
      error: (text) => out.push(text),
      log: (text) => out.push(text),
    });
    expect(code).toBe(1);
    expect(out.join("\n")).toContain("стало 49 (+1)");
  });

  it("новое правило при неизменной сумме -> код 1", async () => {
    const { baseline } = tempTree({ total: 48, byRule: { "react-hooks/exhaustive-deps": 48 } });
    const code = await main([], {
      baselineFile: baseline,
      runEslint: () =>
        fakeEslint({
          warnings: { "react-hooks/exhaustive-deps": 47, "no-console": 1 },
        }),
      log: () => {},
    });
    expect(code).toBe(1);
  });

  it("фатальный ESLint (код 2) -> код 2, а не «ноль предупреждений»", async () => {
    const { baseline } = tempTree({ total: 48, byRule: { "react-hooks/exhaustive-deps": 48 } });
    const out = [];
    const code = await main([], {
      baselineFile: baseline,
      runEslint: () => ({ status: 2, stdout: "", stderr: "bad config", spawnError: undefined }),
      error: (text) => out.push(text),
    });
    expect(code).toBe(2);
    expect(out.join("\n")).toContain("упал фатально");
  });

  it("нет базового файла -> код 2", async () => {
    const { baseline } = tempTree();
    const code = await main([], {
      baselineFile: baseline,
      runEslint: () => fakeEslint({ warnings: {} }),
      error: () => {},
    });
    expect(code).toBe(2);
  });

  it("пустой отчёт ESLint -> код 2 (гейт не должен «позеленеть» на ничем)", async () => {
    const { baseline } = tempTree({ total: 48, byRule: { "react-hooks/exhaustive-deps": 48 } });
    const out = [];
    const code = await main([], {
      baselineFile: baseline,
      runEslint: () => ({ status: 0, stdout: "[]", stderr: "" }),
      error: (text) => out.push(text),
    });
    expect(code).toBe(2);
    expect(out.join("\n")).toContain("ни одного файла");
  });

  it("--update при росте отказывает и не трогает потолок", async () => {
    const { baseline } = tempTree({ total: 48, byRule: { "react-hooks/exhaustive-deps": 48 } });
    const before = fs.readFileSync(baseline, "utf8");
    const out = [];
    const code = await main(["--update"], {
      baselineFile: baseline,
      eslintVersion: "9.39.5",
      runEslint: () => fakeEslint({ warnings: { "react-hooks/exhaustive-deps": 60 } }),
      error: (text) => out.push(text),
    });
    expect(code).toBe(1);
    expect(out.join("\n")).toContain("--update отказался");
    expect(fs.readFileSync(baseline, "utf8")).toBe(before);
  });

  it("--update --force рост фиксирует (осознанный шаг человека)", async () => {
    const { baseline } = tempTree({ total: 48, byRule: { "react-hooks/exhaustive-deps": 48 } });
    const code = await main(["--update", "--force"], {
      baselineFile: baseline,
      eslintVersion: "9.39.5",
      runEslint: () => fakeEslint({ warnings: { "react-hooks/exhaustive-deps": 60 } }),
      log: () => {},
    });
    expect(code).toBe(0);
    expect(JSON.parse(fs.readFileSync(baseline, "utf8"))).toMatchObject({
      total: 60,
      byRule: { "react-hooks/exhaustive-deps": 60 },
    });
  });

  it("--update вниз подтягивает потолок", async () => {
    const { baseline } = tempTree({ total: 48, byRule: { "react-hooks/exhaustive-deps": 48 } });
    const code = await main(["--update"], {
      baselineFile: baseline,
      eslintVersion: "9.39.5",
      runEslint: () => fakeEslint({ warnings: { "react-hooks/exhaustive-deps": 45 } }),
      log: () => {},
    });
    expect(code).toBe(0);
    expect(JSON.parse(fs.readFileSync(baseline, "utf8")).total).toBe(45);
  });
});

describe("закоммиченный базовый файл", () => {
  it("есть и внутренне непротиворечив (сумма по правилам равна total)", () => {
    const raw = JSON.parse(fs.readFileSync(BASELINE_PATH, "utf8"));
    expect(raw.total).toBeGreaterThan(0);
    const sum = Object.values(raw.byRule).reduce((a, b) => a + b, 0);
    expect(sum).toBe(raw.total);
    expect(raw.measuredAt).toMatch(/^\d{4}-\d{2}-\d{2}$/);
  });
});
