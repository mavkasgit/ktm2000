/**
 * Адаптер семафора E2E (#281): дефолты прогона и префикс строк ожидания.
 *
 * Механика самих слотов (`tryAcquireSlot`/`releaseSlot`/`describeHolders`)
 * живёт в `scripts/heavy-core.mjs` и проверяется там же,
 * `scripts/heavy-core.test.js`: второй раннер тех же проверок здесь означал бы,
 * что поведение слота описано дважды и разъедется при первой правке.
 */
import fs from "node:fs";
import os from "node:os";
import path from "node:path";

import { afterEach, describe, expect, it } from "vitest";

import { releaseSlot, tryAcquireSlot } from "../../scripts/heavy-core.mjs";
import { acquireSlot, defaultSlotsDir, resolveMaxRuns } from "./run-slots.mjs";

const dirs: string[] = [];

function tempDir(): string {
  const dir = fs.mkdtempSync(path.join(os.tmpdir(), "ktm2000-slots-"));
  dirs.push(dir);
  return dir;
}

afterEach(() => {
  while (dirs.length > 0) {
    fs.rmSync(dirs.pop() as string, { recursive: true, force: true });
  }
});

describe("resolveMaxRuns", () => {
  it("по умолчанию — два прогона на машину", () => {
    expect(resolveMaxRuns({})).toBe(2);
  });

  it("читает E2E_MAX_PARALLEL_RUNS", () => {
    expect(resolveMaxRuns({ E2E_MAX_PARALLEL_RUNS: "1" })).toBe(1);
    expect(resolveMaxRuns({ E2E_MAX_PARALLEL_RUNS: "4" })).toBe(4);
  });

  it("отвергает не-целое и ноль", () => {
    expect(() => resolveMaxRuns({ E2E_MAX_PARALLEL_RUNS: "0" })).toThrow();
    expect(() => resolveMaxRuns({ E2E_MAX_PARALLEL_RUNS: "два" })).toThrow();
    expect(() => resolveMaxRuns({ E2E_MAX_PARALLEL_RUNS: "1.5" })).toThrow();
  });
});

describe("defaultSlotsDir", () => {
  it("лежит вне репозитория — иначе семафор не видит соседние worktree", () => {
    expect(defaultSlotsDir()).toContain("ktm2000-e2e");
    expect(defaultSlotsDir()).not.toContain("node_modules");
  });
});

describe("acquireSlot", () => {
  it("берёт свободный слот молча и отпускает его", async () => {
    const dir = tempDir();
    const log: string[] = [];
    const slot = await acquireSlot({
      dir,
      payload: { pid: process.pid },
      log: (line: string) => log.push(line),
    });
    expect(slot.index).toBe(0);
    expect(log).toEqual([]);
    releaseSlot(slot);
  });

  it("помечает строки ожидания префиксом [e2e:run]", async () => {
    const dir = tempDir();
    tryAcquireSlot(dir, 1, { pid: process.pid, repo: "чужой" });
    const lines: string[] = [];
    await expect(
      acquireSlot({
        dir,
        max: 1,
        payload: { pid: process.pid },
        waitTimeoutMs: 25,
        pollMs: 5,
        alive: () => true,
        log: (line: string) => lines.push(line),
      }),
    ).rejects.toThrow(/не дождался слота/);
    expect(lines.length).toBeGreaterThan(0);
    expect(lines.every((line) => line.startsWith("[e2e:run] "))).toBe(true);
    expect(lines.join("\n")).toContain("чужой");
  });
});
