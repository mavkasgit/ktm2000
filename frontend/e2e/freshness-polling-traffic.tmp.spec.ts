import type { Page } from "@playwright/test";

import { apiGetSections } from "./api-helpers";
import { test } from "./fixtures";

/**
 * @tmp — ЗАМЕР ТРАФИКА ОПРОСА (фаза 2 свежести, #206).
 *
 * Приём тот же, что в T-208 (`docs/night/tickets/T-208-stale-time-traffic.md`):
 * Playwright на e2e-стенде своего worktree, счёт на стороне клиента
 * (`page.on('request'|'response')`, только `/api/`, байты из `content-length` —
 * uvicorn отвечает без сжатия). Считается не полный трафик экрана, а прибавка
 * опроса: после того как страница устоялась (`networkidle`), экран стоит без
 * действий, и в окне наблюдения видны только запросы таймера `refetchInterval`.
 *
 * Сценарий — «оператор сидит на экране» по 26 с на каждом из трёх
 * операционных экранов (2 полных цикла опроса при 12 с), одним терминалом, а
 * затем двумя вкладками на одном экране. Разница со сценарием T-208 (переходы
 * без остановки, 21 запрос / 17 861 Б, фонового опроса нет) — в том, что там
 * замерялась смена экранов, а здесь — стоянка; они дополняют друг друга.
 */

interface Traffic {
  requests: number;
  bytes: number;
}

function startTracking(page: Page) {
  const state: Traffic = { requests: 0, bytes: 0 };
  const urls: string[] = [];
  // Только бэкенд: модули Vite из `/src/.../api/...` тоже содержат «/api/»,
  // и без этого фильтра в счёт попадал бы код фронтенда.
  const isApi = (url: string) => url.includes("/api/") && !url.includes("/src/");
  page.on("request", (request) => {
    if (!isApi(request.url())) return;
    state.requests += 1;
    urls.push(new URL(request.url()).pathname + new URL(request.url()).search);
  });
  page.on("response", (response) => {
    if (!isApi(response.url())) return;
    const length = Number(response.headers()["content-length"] ?? "0");
    if (Number.isFinite(length)) state.bytes += length;
  });
  return { state, urls };
}

/** Подождать, пока первичная загрузка уляжется: опрос потом виден отдельно. */
async function settle(page: Page) {
  await page.waitForLoadState("networkidle");
  await page.waitForTimeout(1_000);
}

function diff(before: Traffic, after: Traffic): Traffic {
  return { requests: after.requests - before.requests, bytes: after.bytes - before.bytes };
}

/** Запросы окна наблюдения по эндпоинту — видно, что именно перечитал таймер. */
function group(urls: string[], from: number): Record<string, number> {
  const grouped: Record<string, number> = {};
  for (const url of urls.slice(from)) {
    const endpoint = url.split("?")[0];
    grouped[endpoint] = (grouped[endpoint] ?? 0) + 1;
  }
  return grouped;
}

const IDLE_MS = 26_000;

test.describe("@tmp замер трафика опроса операционных экранов", () => {
  test("три экрана, один терминал и две вкладки", async ({ page, loginAsAdmin }) => {
    test.setTimeout(300_000);
    await loginAsAdmin();
    const sections = (await apiGetSections()) as Array<{ id: number; type: string }>;
    const productionSection = sections.find((section) => section.type === "production") ?? sections[0];

    const { state, urls } = startTracking(page);

    // ── Экран 1: Контроль выполнения ──────────────────────────────────────
    await page.goto("/execution");
    await settle(page);
    const executionBefore = { ...state };
    const executionUrlFrom = urls.length;
    await page.waitForTimeout(IDLE_MS);
    const execution = diff(executionBefore, state);
    const executionEndpoints = group(urls, executionUrlFrom);

    // ── Экран 2: Доска участка ────────────────────────────────────────────
    await page.goto(`/section-tasks/${productionSection.id}`);
    await settle(page);
    const boardBefore = { ...state };
    const boardUrlFrom = urls.length;
    await page.waitForTimeout(IDLE_MS);
    const board = diff(boardBefore, state);
    const boardEndpoints = group(urls, boardUrlFrom);

    // ── Экран 3: Передачи ─────────────────────────────────────────────────
    await page.goto("/transfers");
    await settle(page);
    const transfersBefore = { ...state };
    const transfersUrlFrom = urls.length;
    await page.waitForTimeout(IDLE_MS);
    const transfers = diff(transfersBefore, state);
    const transfersEndpoints = group(urls, transfersUrlFrom);

    // ── Две вкладки на одном экране ───────────────────────────────────────
    const second = await page.context().newPage();
    const secondTracker = startTracking(second);
    await page.goto("/execution");
    await second.goto("/execution");
    await settle(page);
    await settle(second);
    const tabsBefore = {
      first: { ...state },
      second: { ...secondTracker.state },
    };
    await page.waitForTimeout(IDLE_MS);
    const tabsFirst = diff(tabsBefore.first, state);
    const tabsSecond = diff(tabsBefore.second, secondTracker.state);

    await second.close();

    console.log(
      "[#206 трафик] " +
        JSON.stringify(
          {
            idleMs: IDLE_MS,
            execution,
            board,
            transfers,
            threeScreensTotal: {
              requests: execution.requests + board.requests + transfers.requests,
              bytes: execution.bytes + board.bytes + transfers.bytes,
            },
            endpoints: {
              execution: executionEndpoints,
              board: boardEndpoints,
              transfers: transfersEndpoints,
            },
            twoTabs: {
              first: tabsFirst,
              second: tabsSecond,
              total: {
                requests: tabsFirst.requests + tabsSecond.requests,
                bytes: tabsFirst.bytes + tabsSecond.bytes,
              },
            },
          },
          null,
          2,
        ),
    );
  });
});
