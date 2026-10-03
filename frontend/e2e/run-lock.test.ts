/**
 * Лок дерева на прогон E2E (#281): подбор лока у мёртвого держателя.
 *
 * Смысл тестов — правило, которого не было до #281: прогон, убитый снаружи
 * (`taskkill`, отмена задачи, падение ОС), оставлял `current.lock` с мёртвым
 * pid, и следующий прогон в этом же worktree ждал освобождения до 40 минут
 * («стек занят прогоном яруса …»). Мёртвого держателя видно по `ESRCH`, и лок
 * снимается сразу; живого — не трогаем до `staleMs`.
 */
import fs from "node:fs";
import os from "node:os";
import path from "node:path";

import { afterEach, describe, expect, it } from "vitest";

import {
  lockFileIn,
  readLock,
  reclaimReason,
  releaseLock,
  tryAcquireLock,
} from "./run-lock.mjs";

const dirs: string[] = [];

function tempDir(): string {
  const dir = fs.mkdtempSync(path.join(os.tmpdir(), "ktm2000-lock-"));
  dirs.push(dir);
  return dir;
}

afterEach(() => {
  while (dirs.length > 0) {
    fs.rmSync(dirs.pop() as string, { recursive: true, force: true });
  }
});

describe("lockFileIn", () => {
  it("лежит в node_modules дерева — лок общий для ярусов, но не для worktree", () => {
    expect(lockFileIn("C:/repo/frontend")).toBe(
      path.join("C:/repo/frontend", "node_modules", ".e2e-run", "current.lock"),
    );
  });
});

describe("tryAcquireLock / releaseLock", () => {
  it("занимает файл один раз: второй писатель получает false", () => {
    const file = lockFileIn(tempDir());
    expect(tryAcquireLock(file, { tier: "smoke", pid: 1, at: 1, runId: "aaaa1111" })).toBe(true);
    expect(tryAcquireLock(file, { tier: "ui-e2e", pid: 2, at: 2, runId: "bbbb2222" })).toBe(false);
    expect(readLock(file)?.tier).toBe("smoke");
  });

  it("освобождённый лок снова свободен", () => {
    const file = lockFileIn(tempDir());
    tryAcquireLock(file, { tier: "smoke", pid: 1, at: 1, runId: "aaaa1111" });
    releaseLock(file);
    expect(readLock(file)).toBeNull();
    expect(tryAcquireLock(file, { tier: "smoke", pid: 2, at: 2, runId: "bbbb2222" })).toBe(true);
  });

  it("битый файл лока считается свободным, а не роняет чтение", () => {
    const file = lockFileIn(tempDir());
    fs.mkdirSync(path.dirname(file), { recursive: true });
    fs.writeFileSync(file, "{не json");
    expect(readLock(file)).toBeNull();
  });
});

describe("reclaimReason", () => {
  it("мёртвый держатель — снимаем сразу и помечаем dead", () => {
    const reason = reclaimReason(
      { tier: "ui-e2e", pid: 424242, at: Date.now(), runId: "dead1234" },
      { alive: () => false },
    );
    expect(reason?.dead).toBe(true);
    expect(reason?.message).toContain("мёртв");
  });

  it("дефолтный now — живой держатель со свежим локом не считается просроченным", () => {
    // Регресс на реальный баг: дефолт был `now = Date.now()` (число), а код
    // звал `now()` — `TypeError: now is not a function` на любом прогоне.
    // Тест зовёт reclaimReason без явного `now`, то есть по умолчанию.
    expect(
      reclaimReason({ tier: "ui-e2e", pid: process.pid, at: Date.now(), runId: "dflt1234" }, { alive: () => true }),
    ).toBeNull();
  });

  it("живой держатель со свежим локом — не трогаем", () => {
    expect(
      reclaimReason(
        { tier: "ui-e2e", pid: process.pid, at: Date.now(), runId: "live1234" },
        { alive: () => true, now: () => Date.now() },
      ),
    ).toBeNull();
  });

  it("живой держатель с просроченным локом — снимаем, но dead = false (клон не сносим)", () => {
    const now = Date.now();
    const reason = reclaimReason(
      { tier: "ui-narrow", pid: process.pid, at: now - 41 * 60_000, runId: "slow1234" },
      { alive: () => true, now: () => now },
    );
    expect(reason?.dead).toBe(false);
    expect(reason?.message).toContain("41 мин");
  });

  it("пустой лок — нечего снимать", () => {
    expect(reclaimReason(null)).toBeNull();
  });

  it("держатель без pid (старый формат) считается мёртвым, но не роняет проверку", () => {
    const reason = reclaimReason({ tier: "smoke", at: Date.now() }, { alive: () => false });
    expect(reason?.dead).toBe(true);
  });
});
