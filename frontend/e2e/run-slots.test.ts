/**
 * Счётный семафор прогонов E2E (#281): слоты, ожидание, подбор чужих слотов.
 *
 * Семафор живёт в `run-slots.mjs` — модуле, а не внутри `run-tier.mjs`, ровно
 * ради этих тестов: логика «сколько прогонов пускать и что делать с чужим
 * слотом» обязана быть проверяемой без запуска Playwright.
 */
import fs from "node:fs";
import os from "node:os";
import path from "node:path";

import { afterEach, describe, expect, it, vi } from "vitest";

import {
  acquireSlot,
  defaultSlotsDir,
  describeHolders,
  releaseSlot,
  resolveMaxRuns,
  slotFile,
  tryAcquireSlot,
} from "./run-slots.mjs";

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

describe("tryAcquireSlot", () => {
  it("занимает слоты по одному и упирается в лимит", () => {
    const dir = tempDir();
    const first = tryAcquireSlot(dir, 2, { pid: process.pid, repo: "a" });
    const second = tryAcquireSlot(dir, 2, { pid: process.pid, repo: "b" });
    expect(first?.index).toBe(0);
    expect(second?.index).toBe(1);
    expect(tryAcquireSlot(dir, 2, { pid: process.pid, repo: "c" })).toBeNull();
  });

  it("освобождённый слот снова свободен", () => {
    const dir = tempDir();
    const slot = tryAcquireSlot(dir, 1, { pid: process.pid });
    expect(slot).not.toBeNull();
    releaseSlot(slot);
    expect(tryAcquireSlot(dir, 1, { pid: process.pid })?.index).toBe(0);
  });

  it("слот мёртвого держателя занимается сразу", () => {
    const dir = tempDir();
    fs.mkdirSync(dir, { recursive: true });
    fs.writeFileSync(slotFile(dir, 0), JSON.stringify({ pid: 424242, at: Date.now() }));
    const slot = tryAcquireSlot(dir, 1, { pid: process.pid }, { alive: () => false });
    expect(slot?.index).toBe(0);
    expect(JSON.parse(fs.readFileSync(slotFile(dir, 0), "utf8")).pid).toBe(process.pid);
  });

  it("живой чужой слот не отнимается", () => {
    const dir = tempDir();
    fs.mkdirSync(dir, { recursive: true });
    const other = { pid: 424242, at: Date.now() };
    fs.writeFileSync(slotFile(dir, 0), JSON.stringify(other));
    expect(tryAcquireSlot(dir, 1, { pid: process.pid }, { alive: () => true })).toBeNull();
    expect(JSON.parse(fs.readFileSync(slotFile(dir, 0), "utf8"))).toEqual(other);
  });
});

describe("acquireSlot", () => {
  it("подбирает просроченный слот и логирует это", async () => {
    const dir = tempDir();
    fs.mkdirSync(dir, { recursive: true });
    fs.writeFileSync(
      slotFile(dir, 0),
      JSON.stringify({ pid: process.pid, at: Date.now() - 10 * 60_000, repo: "старый" }),
    );
    const lines: string[] = [];
    const slot = await acquireSlot({
      dir,
      max: 1,
      payload: { pid: process.pid, repo: "новый" },
      staleMs: 5 * 60_000,
      log: (line: string) => lines.push(line),
    });
    expect(slot.index).toBe(0);
    expect(lines.join("\n")).toContain("просрочен");
    expect(JSON.parse(fs.readFileSync(slotFile(dir, 0), "utf8")).repo).toBe("новый");
  });

  it("ждёт освобождения, показывает держателя и падает по таймауту", async () => {
    const dir = tempDir();
    tryAcquireSlot(dir, 1, { pid: 424242, at: Date.now(), repo: "чужой" });
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
    expect(lines.join("\n")).toContain("чужой");
  });

  it("немедленно отдаёт слот, когда он свободен", async () => {
    const dir = tempDir();
    const log = vi.fn();
    const slot = await acquireSlot({ dir, max: 2, payload: { pid: process.pid }, log });
    expect(slot.index).toBe(0);
    expect(log).not.toHaveBeenCalled();
    releaseSlot(slot);
  });

  it("describeHolders показывает только занятые слоты", () => {
    const dir = tempDir();
    tryAcquireSlot(dir, 2, { pid: 7, repo: "a" });
    const holders = describeHolders(dir, 2, { alive: () => true });
    expect(holders).toHaveLength(1);
    expect(holders[0].holder.repo).toBe("a");
    expect(holders[0].index).toBe(0);
  });
});
