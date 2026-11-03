/**
 * Лок дерева на прогон E2E (#281): подбор лока у мёртвого держателя.
 *
 * Смысл тестов — правило, которого не было до #281: прогон, убитый снаружи
 * (`taskkill`, отмена задачи, падение ОС), оставлял `current.lock` с мёртвым
 * pid, и следующий прогон в этом же worktree ждал освобождения до 40 минут
 * («стек занят прогоном яруса …»). Мёртвого держателя видно по `ESRCH`, и лок
 * снимается сразу; живого — не трогаем никогда, какой бы возраст ни был (#375).
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
  stallNotice,
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

  it("releaseLock чужого лока не сносит — файл уже занят соседом", () => {
    // Лок перешёл к другому прогону (мёртвый держатель снят, сосед занял
    // файл), а прежний прогон в свой finally зовёт releaseLock. Соседский лок
    // должен уцелеть.
    const file = lockFileIn(tempDir());
    tryAcquireLock(file, { tier: "ui-e2e", pid: 111, at: 1, runId: "aaaa1111" });
    // Занятый лок второй раз не пишется — подменяем содержимое файла.
    fs.writeFileSync(file, JSON.stringify({ tier: "smoke", pid: 222, at: 2, runId: "bbbb2222" }));
    releaseLock(file, "aaaa1111");
    expect(readLock(file)?.runId).toBe("bbbb2222");
  });

  it("releaseLock своего лока снимает файл", () => {
    const file = lockFileIn(tempDir());
    tryAcquireLock(file, { tier: "smoke", pid: 1, at: 1, runId: "aaaa1111" });
    releaseLock(file, "aaaa1111");
    expect(readLock(file)).toBeNull();
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

  it("дефолтные зависимости — свой живой pid не считается снятым", () => {
    // Регресс на реальный баг: опции по умолчанию не должны падать — раньше
    // внутри звалось `now()`, при дефолте `Date.now()` (число), и любой прогон
    // ловил `TypeError: now is not a function`. С #375 возраст в этот путь
    // вообще не входит, но дефолтный `alive` (настоящая проверка pid) обязан
    // работать без явных опций.
    expect(
      reclaimReason({ tier: "ui-e2e", pid: process.pid, at: Date.now(), runId: "dflt1234" }),
    ).toBeNull();
  });

  it("живой держатель со свежим локом — не трогаем", () => {
    expect(
      reclaimReason(
        { tier: "ui-e2e", pid: process.pid, at: Date.now(), runId: "live1234" },
        { alive: () => true },
      ),
    ).toBeNull();
  });

  it("живой держатель с просроченным локом — не снимаем: долгий прогон не порча (#375)", () => {
    // Раньше возраст сам по себе был основанием отнять лок, и претендент,
    // дождавшийся дольше `staleMs`, выкидывал ЖИВОЙ прогон из дерева, в котором
    // тот ещё шёл: два прогона делят `node_modules`, кеш браузеров и
    // `test-results`, и вердикт обоих перестаёт что-то значить. Отныне возраст
    // — только повод предупредить; снимается лишь мёртвый держатель.
    const now = Date.now();
    expect(
      reclaimReason(
        { tier: "ui-narrow", pid: process.pid, at: now - 41 * 60_000, runId: "slow1234" },
        { alive: () => true },
      ),
    ).toBeNull();
  });

  it("stallNotice: живой держатель старше порога — предупреждает по имени и возрасту", () => {
    const now = Date.now();
    const notice = stallNotice(
      { tier: "ui-narrow", pid: 4242, at: now - 41 * 60_000, runId: "slow1234" },
      { staleMs: 40 * 60_000, now: () => now, alive: () => true },
    );
    expect(notice?.message).toContain("4242");
    expect(notice?.message).toContain("41 мин");
    expect(notice?.ageMs).toBe(41 * 60_000);
  });

  it("stallNotice: свежий живой лок и мёртвый держатель — молчат", () => {
    const now = Date.now();
    expect(
      stallNotice({ pid: 4242, at: now - 60_000 }, { staleMs: 40 * 60_000, now: () => now, alive: () => true }),
    ).toBeNull();
    // Мёртвого описывает reclaimReason, а не предупреждение о зависании.
    expect(
      stallNotice({ pid: 4242, at: now - 99 * 60_000 }, { staleMs: 40 * 60_000, now: () => now, alive: () => false }),
    ).toBeNull();
    expect(stallNotice(null)).toBeNull();
  });

  it("пустой лок — нечего снимать", () => {
    expect(reclaimReason(null)).toBeNull();
  });

  it("держатель без pid (старый формат) считается мёртвым, но не роняет проверку", () => {
    const reason = reclaimReason({ tier: "smoke", at: Date.now() }, { alive: () => false });
    expect(reason?.dead).toBe(true);
  });
});
