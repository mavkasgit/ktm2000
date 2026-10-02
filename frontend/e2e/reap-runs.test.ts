/**
 * Уборка клонов прогона, умершего в чужом worktree (#306).
 *
 * Проверяется то, ради чего модуль и выделен: **кого уборщик трогать не
 * вправе**. Всё остальное — вызов `e2e-db.py drop` — проверяется демонстрацией
 * на живом Postgres, здесь достаточно контракта «кому звать и кого не звать».
 *
 * Правило, которое обязано остаться: уборка идёт по списку слотов, уже
 * отобранных как мёртвые. Сам модуль живость не проверяет — этим занят
 * `run-slots.mjs` (`process.kill(pid, 0)`), и повторная проверка здесь была бы
 * второй, независимой, которая завтра разойдётся с первой.
 */
import fs from "node:fs";
import os from "node:os";
import path from "node:path";

import { afterEach, describe, expect, it, vi } from "vitest";

import { cleanupAbandonedRuns } from "./reap-runs.mjs";

const dirs: string[] = [];

function tempRepo(): string {
  const repo = fs.mkdtempSync(path.join(os.tmpdir(), "ktm2000-reap-"));
  fs.mkdirSync(path.join(repo, "scripts"), { recursive: true });
  fs.writeFileSync(path.join(repo, "scripts", "e2e-db.py"), "# stub\n");
  dirs.push(repo);
  return repo;
}

function standEnv(repo: string): string {
  const file = path.join(repo, ".env.e2e.local");
  fs.writeFileSync(file, "DATABASE_URL=postgresql://u:p@localhost:5441/db\n");
  return file;
}

/** Заглушка запуска: запоминает вызовы и всегда успешна. */
function stubRun() {
  const calls: { script: string; args: string[] }[] = [];
  const run = vi.fn((cmd: string, args: string[], opts: { cwd: string }) => {
    calls.push({ script: args[0], args });
    return { status: 0, stdout: `[e2e-db] ок (${opts.cwd})\n`, stderr: "" };
  });
  return { calls, run };
}

afterEach(() => {
  while (dirs.length) fs.rmSync(dirs.pop()!, { recursive: true, force: true });
});

describe("cleanupAbandonedRuns", () => {
  it("сносит клоны прогона, чей слот отобран как мёртвый", () => {
    const repo = tempRepo();
    const { calls, run } = stubRun();

    const result = cleanupAbandonedRuns(
      [{ repo, runId: "abcd12", envFile: standEnv(repo), pid: 999999 }],
      { ownRunId: "myOwnRun", run, log: () => {} },
    );

    expect(result.cleaned).toEqual(["abcd12"]);
    expect(result.failed).toEqual([]);
    expect(calls).toHaveLength(1);
    expect(calls[0].args).toContain("--run-id");
    expect(calls[0].args).toContain("abcd12");
  });

  it("не трогает прогон, чей слот живой: его в список не отдали", () => {
    const repo = tempRepo();
    const { calls, run } = stubRun();

    // Пустой список — ни одного отобранного слота: уборщик не должен рыться
    // по семафору сам, иначе он снёс бы клоны идущего прогона.
    const result = cleanupAbandonedRuns([], { ownRunId: "myOwnRun", run, log: () => {} });

    expect(calls).toHaveLength(0);
    expect(result.cleaned).toEqual([]);
  });

  it("не трогает собственный прогон по совпадению runId", () => {
    const repo = tempRepo();
    const { calls, run } = stubRun();

    const result = cleanupAbandonedRuns(
      [{ repo, runId: "myOwnRun", envFile: standEnv(repo), pid: 999999 }],
      { ownRunId: "myOwnRun", run, log: () => {} },
    );

    expect(calls).toHaveLength(0);
    expect(result.cleaned).toEqual([]);
    expect(result.skipped.join(" ")).toContain("свой прогон");
  });

  it("пропускает слот без repo или runId, а не гадает", () => {
    const { calls, run } = stubRun();

    const result = cleanupAbandonedRuns([{ pid: 999999 }], {
      ownRunId: "myOwnRun",
      run,
      log: () => {},
    });

    expect(calls).toHaveLength(0);
    expect(result.skipped).toHaveLength(1);
  });

  it("пропускает чужое дерево без scripts/e2e-db.py", () => {
    const bare = fs.mkdtempSync(path.join(os.tmpdir(), "ktm2000-bare-"));
    dirs.push(bare);
    const { calls, run } = stubRun();

    const result = cleanupAbandonedRuns([{ repo: bare, runId: "abcd12", pid: 1 }], {
      ownRunId: "myOwnRun",
      run,
      log: () => {},
    });

    expect(calls).toHaveLength(0);
    expect(result.skipped.join(" ")).toContain("нечего убирать");
  });

  it("сообщает о сбое, не выдавая его за успех", () => {
    const repo = tempRepo();
    const run = vi.fn(() => ({ status: 1, stdout: "", stderr: "нет доступа" }));

    const result = cleanupAbandonedRuns([{ repo, runId: "abcd12", envFile: standEnv(repo) }], {
      ownRunId: "myOwnRun",
      run,
      log: () => {},
    });

    expect(result.cleaned).toEqual([]);
    expect(result.failed).toEqual(["abcd12"]);
  });
});