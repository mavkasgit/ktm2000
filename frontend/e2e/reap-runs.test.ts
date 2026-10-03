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

  it("относительный env-файл ищет в корне ЧУЖОГО дерева, а не в текущем", () => {
    // Регресс на реальный баг #306: `E2E_ENV_FILE` по конвенции относителен
    // и отсчитывается от корня репозитория (`e2e/AGENTS.md`), то есть от
    // `repo` отобранного слота. Проверка «env-файл есть» смотрела в текущем
    // каталоге уборщика, где чужого файла нет, — и уборка молча пропускалась
    // целиком, то есть ровно тот случай, ради которого модуль написан.
    const foreign = tempRepo();
    standEnv(foreign);
    const { calls, run } = stubRun();

    // Текущий каталог уборщика — отдельное дерево без `.env.e2e.local`.
    const reaper = tempRepo();
    const previousCwd = process.cwd();
    process.chdir(reaper);
    try {
      const result = cleanupAbandonedRuns(
        [{ repo: foreign, runId: "bead34", envFile: ".env.e2e.local", pid: 999999 }],
        { ownRunId: "myOwnRun", run, log: () => {} },
      );

      expect(result.cleaned).toEqual(["bead34"]);
      expect(result.skipped).toEqual([]);
      expect(calls).toHaveLength(1);
      // Скрипту уходит путь в его собственном дереве, а не путь уборщика.
      expect(calls[0].args).toContain(path.join(foreign, ".env.e2e.local"));
    } finally {
      process.chdir(previousCwd);
    }
  });
});