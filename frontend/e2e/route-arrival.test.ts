/**
 * Поведение перехода на маршрут в E2E (#289).
 *
 * Зачем модуль отдельный: серия прогонов с `--workers=2` дала 1 падение из 10 —
 * после `page.goto("/section-tasks")` заголовок «Участки» не появился за 10 с, а
 * на скриншоте остался прежний маршрут с открытым модальным окном, то есть
 * документ, судя по всему, не сменился вовсе. Проверить это можно только
 * прогоном стенда, а вот правило «что делать, если документ не сменился» —
 * здесь, юнит-тестом с поддельной страницей: у настоящего `page` нет способа
 * заставить `goto` молча ничего не сделать.
 *
 * Поддельная страница — не «мок внутренностей»: `gotoRoute` работает через
 * публичный интерфейс Playwright (`goto`, `evaluate`), и тест проверяет именно
 * поведение (сколько переходов, с каким бюджетом ждали маршрут, что проброшено
 * наружу), а не устройство цикла.
 */
import { describe, expect, it, vi } from "vitest";

import {
  ARRIVAL_BUDGET_MS,
  MAX_ARRIVAL_ATTEMPTS,
  RENAVIGATE_BUDGET_MS,
  documentWasReplaced,
  isTransientNavigationError,
  gotoRoute,
} from "./route-arrival.mjs";

type FakeOptions = {
  /** Значения `performance.timeOrigin` по порядку; `null` — `evaluate` упал. */
  origins?: Array<number | null>;
  /** Поведение `goto`: индекс попытки (с 1), url. */
  gotoImpl?: (url: string, attempt: number) => void;
};

function fakePage({ origins = [], gotoImpl }: FakeOptions) {
  const queue = [...origins];
  const gotoUrls: string[] = [];
  const page = {
    async goto(url: string) {
      gotoUrls.push(url);
      gotoImpl?.(url, gotoUrls.length);
      return null;
    },
    async evaluate<T>(_fn: () => T): Promise<T> {
      // Пустая очередь — как оборванный execution context: значение неизвестно.
      if (queue.length === 0) throw new Error("Execution context was destroyed");
      const next = queue.shift();
      if (next === null) throw new Error("Execution context was destroyed");
      return next as T;
    },
  };
  return { page, gotoUrls };
}

describe("isTransientNavigationError", () => {
  it("обрыв соединения с dev-сервером — временный", () => {
    for (const message of [
      "page.goto: net::ERR_CONNECTION_RESET at http://127.0.0.1:1/section-tasks",
      "page.goto: net::ERR_CONNECTION_REFUSED",
      "page.goto: net::ERR_CONNECTION_TIMED_OUT",
      "page.goto: net::ERR_NETWORK_CHANGED",
    ]) {
      expect(isTransientNavigationError(message), message).toBe(true);
    }
  });

  it("отменённый переход и таймаут — не временные: их не прячем ретраем", () => {
    for (const message of [
      "page.goto: net::ERR_ABORTED at http://127.0.0.1:1/section-tasks",
      "page.goto: Timeout 60000ms exceeded",
      "locator.click: Target closed",
    ]) {
      expect(isTransientNavigationError(message), message).toBe(false);
    }
  });
});

describe("documentWasReplaced", () => {
  it("разные timeOrigin — документ новый, одинаковые — тот же", () => {
    expect(documentWasReplaced(1000, 2000)).toBe(true);
    expect(documentWasReplaced(1000, 1000)).toBe(false);
  });

  it("неизвестное значение не выдаётся за «документ сменился»", () => {
    // Знание потеряно (execution context ушёл) — решение принимает маршрут,
    // а не догадка: считаем документ новым и ждём заголовок, как раньше.
    expect(documentWasReplaced(null, 2000)).toBe(true);
    expect(documentWasReplaced(1000, null)).toBe(true);
  });
});

describe("gotoRoute", () => {
  const url = "/section-tasks";

  it("документ сменился и маршрут смонтировался — один переход", async () => {
    const { page, gotoUrls } = fakePage({ origins: [1, 2] });
    const waitForRoute = vi.fn(async () => true);

    await gotoRoute(page, url, { waitForRoute });

    expect(gotoUrls).toEqual([url]);
    expect(waitForRoute).toHaveBeenCalledTimes(1);
    expect(waitForRoute).toHaveBeenCalledWith(ARRIVAL_BUDGET_MS);
  });

  it("документ не сменился — переход повторяется, а не ждём маршрут в старом", async () => {
    // попытка 1: before=1, after=1 (тот же документ); попытка 2: before=1, after=2
    const { page, gotoUrls } = fakePage({ origins: [1, 1, 1, 2] });
    const waitForRoute = vi.fn(async () => true);

    await gotoRoute(page, url, { waitForRoute });

    expect(gotoUrls).toEqual([url, url]);
    // В старом документе маршрута нового адреса не будет: ждать там нечего.
    expect(waitForRoute).toHaveBeenCalledTimes(1);
    expect(waitForRoute).toHaveBeenCalledWith(RENAVIGATE_BUDGET_MS);
  });

  it("документ новый, но маршрут не смонтировался — перезагрузка и второй бюджет", async () => {
    const { page, gotoUrls } = fakePage({ origins: [1, 2, 3, 4] });
    const waitForRoute = vi.fn();
    waitForRoute.mockResolvedValueOnce(false).mockResolvedValueOnce(true);

    await gotoRoute(page, url, { waitForRoute });

    expect(gotoUrls).toEqual([url, url]);
    expect(waitForRoute.mock.calls).toEqual([[ARRIVAL_BUDGET_MS], [RENAVIGATE_BUDGET_MS]]);
  });

  it(`попыток не больше ${MAX_ARRIVAL_ATTEMPTS}, и последняя не бросает`, async () => {
    const { page, gotoUrls } = fakePage({ origins: [1, 2, 3, 4] });
    const waitForRoute = vi.fn(async () => false);

    await expect(gotoRoute(page, url, { waitForRoute })).resolves.toBeUndefined();

    expect(gotoUrls).toHaveLength(MAX_ARRIVAL_ATTEMPTS);
    expect(waitForRoute).toHaveBeenCalledTimes(MAX_ARRIVAL_ATTEMPTS);
  });

  it("временный обрыв dev-сервера — один повтор перехода", async () => {
    const { page, gotoUrls } = fakePage({
      origins: [1, 2],
      gotoImpl: (_url, attempt) => {
        if (attempt === 1) throw new Error("page.goto: net::ERR_CONNECTION_RESET");
      },
    });
    const waitForRoute = vi.fn(async () => true);
    const sleep = vi.fn(async () => {});

    await gotoRoute(page, url, { waitForRoute, sleep });

    expect(gotoUrls).toHaveLength(2);
    expect(sleep).toHaveBeenCalledTimes(1);
    expect(waitForRoute).toHaveBeenCalledWith(ARRIVAL_BUDGET_MS);
  });

  it("не временная ошибка перехода — наружу, без повтора", async () => {
    const { page, gotoUrls } = fakePage({
      gotoImpl: () => {
        throw new Error("page.goto: net::ERR_ABORTED");
      },
    });
    const waitForRoute = vi.fn(async () => true);
    const sleep = vi.fn(async () => {});

    await expect(gotoRoute(page, url, { waitForRoute, sleep })).rejects.toThrow(/ERR_ABORTED/);

    expect(gotoUrls).toHaveLength(1);
    expect(waitForRoute).not.toHaveBeenCalled();
    expect(sleep).not.toHaveBeenCalled();
  });

  it("timeOrigin неизвестен — маршрут всё равно ждём", async () => {
    const { page } = fakePage({ origins: [null, null] });
    const waitForRoute = vi.fn(async () => true);

    await gotoRoute(page, url, { waitForRoute });

    expect(waitForRoute).toHaveBeenCalledTimes(1);
    expect(waitForRoute).toHaveBeenCalledWith(ARRIVAL_BUDGET_MS);
  });
});
