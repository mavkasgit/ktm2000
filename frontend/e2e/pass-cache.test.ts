/**
 * Кеш «уже проходил» и флейк.
 *
 * Проверяем ровно то, что решает тикет #224: зелёный результат, полученный с
 * ретрая, обязан ОСТАВАТЬСЯ в кеше (результат-то настоящий), но НЕ давать
 * права на пропуск в следующем прогоне. Если этот контракт развалится, флейк
 * снова станет «проверенным» и выпадет из проверки навсегда, а прогон с
 * `retries: 2` в CI будет читаться как зелёный.
 */
import fs from "node:fs";
import os from "node:os";
import path from "node:path";
import { afterEach, beforeEach, describe, expect, it } from "vitest";

import { PassCache } from "./pass-cache";

const VERSION = "test-version";
const FLAKY = "smoke:reversal-journal › @smoke › отмена";
const CLEAN = "smoke:final-release › @smoke › выпуск";

let dir = "";
let cacheFile = "";

beforeEach(() => {
  dir = fs.mkdtempSync(path.join(os.tmpdir(), "e2e-pass-cache-"));
  cacheFile = path.join(dir, "e2e-passed.json");
});

afterEach(() => {
  fs.rmSync(dir, { recursive: true, force: true });
});

/** Новый экземпляр на чистом файле: состояние `loaded` живёт в объекте. */
function freshCache(): PassCache {
  return new PassCache({ file: cacheFile, version: VERSION, enabled: true });
}

function readEntry(key: string): Record<string, unknown> {
  const file = JSON.parse(fs.readFileSync(cacheFile, "utf8")) as {
    entries: Record<string, Record<string, unknown>>;
  };
  return file.entries[key];
}

describe("кеш «уже проходил»", () => {
  it("чистый зелёный пропускается в следующем прогоне", () => {
    const cache = freshCache();

    cache.record(CLEAN, "passed");

    // Читаем файл заново, а не спрашиваем тот же объект: кеш живёт между
    // прогонами, и решает именно то, что он записал на диск.
    expect(freshCache().alreadyPassed(CLEAN)).toBe(true);
    expect(readEntry(CLEAN).passedOnRetry).toBeUndefined();
  });

  it("зелёный не с первой попытки записывается, но не пропускается", () => {
    freshCache().record(FLAKY, "passed", 1);

    // Запись есть — результат зелёный и терять его незачем.
    expect(readEntry(FLAKY).status).toBe("passed");
    expect(readEntry(FLAKY).passedOnRetry).toBe(true);
    // А пропускать её нельзя: тест обязан снова отработать на этой же версии.
    expect(freshCache().alreadyPassed(FLAKY)).toBe(false);
  });

  it("пометка снимается, когда флейк прошёл чисто, и тест снова пропускается", () => {
    const first = freshCache();
    first.record(FLAKY, "passed", 1);
    expect(first.alreadyPassed(FLAKY)).toBe(false);

    // Следующий прогон на той же версии: попытка красная, потом зелёная.
    const second = freshCache();
    second.record(FLAKY, "failed");
    second.record(FLAKY, "passed");

    expect(readEntry(FLAKY).passedOnRetry).toBeUndefined();
    expect(second.alreadyPassed(FLAKY)).toBe(true);
  });

  it("красная попытка с ретраем не проходит за зелёную", () => {
    freshCache().record(FLAKY, "failed", 1);

    const entry = readEntry(FLAKY);
    expect(entry.status).toBe("failed");
    expect(entry.passedOnRetry).toBeUndefined();
    expect(freshCache().alreadyPassed(FLAKY)).toBe(false);
  });

  it("счётчик зелёных показывает ровно то, что будет пропущено", () => {
    const cache = freshCache();
    cache.record(CLEAN, "passed");
    cache.record(FLAKY, "passed", 1);

    // Флейк в счётчик не идёт: он не пропускается, и называть его зелёным
    // в причине пропуска («зелёных в кеше: N») было бы враньём.
    expect(cache.knownCount()).toBe(1);
  });

  it("без флага E2E_SKIP_PASSED кеш не пишет ничего", () => {
    const cache = new PassCache({ file: cacheFile, version: VERSION, enabled: false });

    cache.record(CLEAN, "passed");

    expect(fs.existsSync(cacheFile)).toBe(false);
    expect(cache.alreadyPassed(CLEAN)).toBe(false);
  });
});
