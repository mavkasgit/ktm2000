/**
 * Слот воркера E2E (#289): `parallelIndex`, а не `workerIndex` и не остаток.
 *
 * Что охраняет тест
 * -----------------
 * Инвариант один: два **живых** воркера не могут получить один слот, потому
 * что слот — это адрес клона БД и backend'а, а `apiResetAll()` в `beforeEach`
 * делает `TRUNCATE … CASCADE`. Нарушение видно не как «неудобно», а как
 * `UniqueViolation uq_product_dimensions_product_type`: два воркера сеяли одну
 * БД (полный прогон `--workers=2`, живая пара `workerIndex` `{0, 2}`).
 *
 * Проверить «живость» в юнит-тесте нельзя, поэтому проверяется то, из чего
 * она следует: слот берётся из `parallelIndex` (документированная гарантия
 * уникальности среди одновременно работающих воркеров) и **не** зависит от
 * сквозного `workerIndex`; выход за диапазон — ошибка, а не тихий остаток.
 */
import { describe, expect, it } from "vitest";

import { readParallelIndex, workerBackendUrls, workerSlot } from "./worker-slot";

describe("workerSlot", () => {
  it("слот равен parallelIndex: перестановки нет", () => {
    for (let index = 0; index < 4; index += 1) {
      expect(workerSlot(index, 4)).toBe(index);
    }
  });

  it("живая пара воркеров получает разные слоты (регресс {0, 2} → slot 0)", () => {
    // Старая формула `workerIndex % 2` на живой паре {0, 2} давала 0 и 0 —
    // отсюда гонка сидов. `parallelIndex` у этой пары разный по контракту
    // Playwright, поэтому и слоты разные.
    const live = [workerSlot(0, 2), workerSlot(1, 2)];
    expect(new Set(live).size).toBe(2);
    expect(live).toEqual([0, 1]);
  });

  it("слот не читает workerIndex: воркер с индексом 2 и слотом 1 идёт в 1", () => {
    const env = { TEST_WORKER_INDEX: "2", TEST_PARALLEL_INDEX: "1" };
    expect(workerSlot(readParallelIndex(env), 2)).toBe(1);
  });

  it("слот переиспользуется после смерти воркера: серия 0,1,0,1 — та же карта", () => {
    const series = [0, 1, 0, 1, 0, 1];
    expect(series.map((index) => workerSlot(index, 2))).toEqual(series);
  });

  it("parallelIndex вне диапазона — ошибка, а не остаток по модулю", () => {
    expect(() => workerSlot(2, 2)).toThrow(/клонов БД и backend'ов выдано меньше/);
    expect(() => workerSlot(5, 1)).toThrow(/parallelIndex=5/);
  });

  it("нечисло и отрицательное значение — ошибка", () => {
    expect(() => workerSlot(-1, 2)).toThrow(/неотрицательным целым/);
    expect(() => workerSlot(1.5, 4)).toThrow(/неотрицательным целым/);
    expect(() => workerSlot(Number.NaN, 4)).toThrow(/неотрицательным целым/);
  });
});

describe("readParallelIndex", () => {
  it("читает TEST_PARALLEL_INDEX", () => {
    expect(readParallelIndex({ TEST_PARALLEL_INDEX: "3" })).toBe(3);
    expect(readParallelIndex({ TEST_PARALLEL_INDEX: " 1 " })).toBe(1);
  });

  it("вне воркерного процесса — слот 0 (одиночный прогон, конфиг, юнит-тесты)", () => {
    expect(readParallelIndex({})).toBe(0);
    expect(readParallelIndex({ TEST_PARALLEL_INDEX: "" })).toBe(0);
  });

  it("воркерный процесс без TEST_PARALLEL_INDEX — ошибка, а не слот 0", () => {
    // Иначе два живых воркера молча уехали бы в один слот — ровно та гонка.
    expect(() => readParallelIndex({ TEST_WORKER_INDEX: "0" })).toThrow(
      /не поставил TEST_PARALLEL_INDEX/,
    );
  });

  it("мусор в TEST_PARALLEL_INDEX — ошибка", () => {
    expect(() => readParallelIndex({ TEST_PARALLEL_INDEX: "1.5" })).toThrow(/неотрицательным/);
    expect(() => readParallelIndex({ TEST_PARALLEL_INDEX: "one" })).toThrow(/неотрицательным/);
    expect(() => readParallelIndex({ TEST_PARALLEL_INDEX: "-1" })).toThrow(/неотрицательным/);
  });
});

describe("workerBackendUrls", () => {
  it("берёт список адресов из E2E_WORKER_API_URLS", () => {
    const urls = ["http://127.0.0.1:5001/api", "http://127.0.0.1:5002/api"];
    expect(workerBackendUrls({ E2E_WORKER_API_URLS: JSON.stringify(urls) })).toEqual(urls);
  });

  it("без списка — один адрес из E2E_API_URL", () => {
    expect(workerBackendUrls({ E2E_API_URL: "http://127.0.0.1:5001/api" })).toEqual([
      "http://127.0.0.1:5001/api",
    ]);
    expect(workerBackendUrls({})).toEqual([""]);
  });
});
