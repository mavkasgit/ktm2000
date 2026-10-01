/**
 * @tmp Замер трафика при `staleTime` 3 с и 5 мин (#208).
 *
 * Тикет ничего не переключает: `frontend/src/app/main.tsx` остаётся `1000 * 3`.
 * Второй режим включается **только в этом сценарии** — перехватом модуля
 * `main.tsx` у dev-сервера и подменой поля `staleTime` (`1e3 * 3` → `1e3 * 300`
 * — esbuild отдаёт литерал именно так). Продуктовый код не меняется.
 *
 * Сценарий (шаги фиксированы, иначе замер несравним):
 *   вход → доска участка → контроль выполнения → передачи → справочник сырья →
 *   планирование (первый проход по разделам), затем повторный заход на контроль
 *   выполнения и доску участка («перечитывание того же экрана»), затем отдельный
 *   прогон с двумя вкладками. Никаких бизнес-действий — только переходы.
 *
 * Переходы — клики по пунктам бокового меню (клиентский роутинг): `page.goto`
 * перезагружал бы приложение и обнулял кеш React Query, из-за чего `staleTime`
 * не влиял бы ни на что и замер был бы не про него.
 *
 * Считаем запросы к `/api/*`: метод, путь, статус, байты ответа
 * (`content-length`, иначе длина тела) — с разбивкой по шагу сценария.
 *
 * Запуск:
 *   E2E_TMP=1 npm --prefix frontend run test:e2e -- \
 *     e2e/traffic-stale-time.tmp.spec.ts --project=tmp --retries=0
 */

import type { Page } from "@playwright/test";

import { apiResetAll } from "./api-helpers";
import { test, expect } from "./fixtures";

const STALE_3S = 1000 * 3;
const STALE_5MIN = 1000 * 300;

/** Цепочка шагов: подпись пункта меню — как её видит оператор. */
const CHAIN = [
  { step: "доска участка", link: "Участки" },
  { step: "контроль выполнения", link: "Контроль выполнения" },
  { step: "передачи", link: "Передачи" },
  { step: "справочник сырья", link: "Справочники" },
  { step: "планирование", link: "План" },
  { step: "повтор: контроль выполнения", link: "Контроль выполнения" },
  { step: "повтор: доска участка", link: "Участки" },
] as const;

interface Rec {
  step: string;
  method: string;
  path: string;
  status: number;
  bytes: number;
}

interface Summary {
  total: number;
  unique: number;
  bytes: number;
  byStep: Map<string, { n: number; bytes: number }>;
  api: Rec[];
}

interface Tracker {
  recs: Rec[];
  setStep: (next: string) => void;
}

function tracker(page: Page): Tracker {
  const recs: Rec[] = [];
  const byRequest = new Map<unknown, Rec>();
  let step = "вход";
  page.on("request", (request) => {
    let url: URL;
    try {
      url = new URL(request.url());
    } catch {
      return;
    }
    if (!url.pathname.startsWith("/api/")) return;
    const rec: Rec = {
      step,
      method: request.method(),
      path: url.pathname + url.search,
      status: 0,
      bytes: 0,
    };
    recs.push(rec);
    byRequest.set(request, rec);
  });
  page.on("response", (response) => {
    const rec = byRequest.get(response.request());
    if (!rec) return;
    rec.status = response.status();
    const header = Number(response.headers()["content-length"] ?? 0);
    if (Number.isFinite(header) && header > 0) {
      rec.bytes = header;
      return;
    }
    void response
      .body()
      .then((body) => {
        rec.bytes = body.length;
      })
      .catch(() => {});
  });
  return {
    recs,
    setStep: (next: string) => {
      step = next;
    },
  };
}

/** Подменяет `staleTime` в `main.tsx` на dev-сервере (только для замера). */
async function overrideStaleTime(page: Page, ms: number, applied: { ok: boolean }) {
  if (ms === STALE_3S) {
    applied.ok = true;
    return;
  }
  await page.route("**/src/app/main.tsx*", async (route) => {
    const response = await route.fetch();
    let body = await response.text();
    // Vite/esbuild отдаёт литерал как `1e3 * 3`, поэтому цепляемся за само
    // поле `staleTime`, а не за исходное выражение из main.tsx.
    if (!/staleTime:\s*[^,\n]+/.test(body)) {
      applied.ok = false;
      await route.fulfill({ response, body });
      return;
    }
    body = body.replace(/staleTime:\s*[^,\n]+/, `staleTime: 1e3 * ${ms / 1000}`);
    applied.ok = body.includes(`staleTime: 1e3 * ${ms / 1000}`);
    const headers = { ...response.headers() };
    delete headers["content-length"];
    delete headers["content-encoding"];
    await route.fulfill({ status: response.status(), headers, body });
  });
}

async function settle(page: Page, ms = 1_500) {
  await page.waitForTimeout(ms);
}

/** Переход по разделу кликом в боковом меню (клиентский роутинг). */
async function navigateByMenu(page: Page, label: string) {
  const link = page.getByRole("link", { name: label, exact: true }).first();
  // Справочник ролей приезжает асинхронно: до него пункты меню скрыты.
  await expect(link).toBeVisible({ timeout: 20_000 });
  await link.click();
}

function summarize(recs: Rec[]): Summary {
  const unique = new Set(recs.map((r) => `${r.method} ${r.path}`));
  const bytes = recs.reduce((sum, r) => sum + r.bytes, 0);
  const byStep = new Map<string, { n: number; bytes: number }>();
  for (const rec of recs) {
    const cur = byStep.get(rec.step) ?? { n: 0, bytes: 0 };
    cur.n += 1;
    cur.bytes += rec.bytes;
    byStep.set(rec.step, cur);
  }
  return { total: recs.length, unique: unique.size, bytes, byStep, api: recs };
}

function report(label: string, summary: Summary) {
  console.log(`\n=== ЗАМЕР ${label} ===`);
  console.log(
    `запросов к API: ${summary.total}, уникальных URL: ${summary.unique}, байт: ${summary.bytes}`,
  );
  for (const [step, value] of summary.byStep) {
    console.log(`  ${step}: ${value.n} запросов, ${value.bytes} Б`);
  }
  for (const rec of summary.api) {
    console.log(`    ${rec.method} ${rec.path} → ${rec.status}, ${rec.bytes} Б [${rec.step}]`);
  }
}

test.describe("@tmp @замер-трафика #208", () => {
  test.beforeEach(async ({ page, loginAsAdmin }) => {
    await loginAsAdmin();
    await apiResetAll();
  });

  for (const mode of [STALE_3S, STALE_5MIN]) {
    const label = mode < 60_000 ? `staleTime ${mode / 1000} с` : `staleTime ${mode / 60_000} мин`;
    test(`трафик: ${label}`, async ({ page }) => {
      test.setTimeout(240_000);
      const applied = { ok: false };
      await overrideStaleTime(page, mode, applied);
      const track = tracker(page);

      // Прогрев вне цепочки: обзорная страница, её трафик в зачёт не идёт.
      await page.goto("/");
      await settle(page);
      const warmup = summarize(track.recs);
      track.recs.length = 0;

      for (const { step, link } of CHAIN) {
        track.setStep(step);
        await navigateByMenu(page, link);
        await settle(page);
      }

      const chainSummary = summarize(track.recs);
      expect(applied.ok, "подмена staleTime в main.tsx не применилась").toBe(true);
      report(label, chainSummary);
      test.info().attach(`трафик-${mode}.json`, {
        body: JSON.stringify(
          { label, applied: applied.ok, warmup: warmup.total, chain: chainSummary.api },
          null,
          2,
        ),
        contentType: "application/json",
      });
    });
  }

  test("трафик: две вкладки на одном стенде (staleTime 3 с) [two-tabs]", async ({ page }) => {
    test.setTimeout(240_000);
    const track1 = tracker(page);
    await page.goto("/");
    await settle(page);
    await navigateByMenu(page, "Контроль выполнения");
    await settle(page);
    const tab1 = summarize(track1.recs);

    const page2 = await page.context().newPage();
    await page2.goto("/");
    await settle(page2);
    const track2 = tracker(page2);
    for (const { step, link } of CHAIN) {
      track2.setStep(step);
      await navigateByMenu(page2, link);
      await settle(page2);
    }
    const tab2 = summarize(track2.recs);

    // Возврат фокуса на первую вкладку: `refetchOnWindowFocus` не переопределён
    // (дефолт TanStack Query — true), поэтому при `staleTime` 3 с вкладка
    // должна перечитать то, что протухло, пока фокус был у соседней.
    track1.recs.length = 0;
    track1.setStep("возврат фокуса на вкладку 1");
    await page.bringToFront();
    await settle(page, 3_000);
    const focus = summarize(track1.recs);

    report("вкладка 1 (вход в контроль выполнения)", tab1);
    report("вкладка 2 (полный проход)", tab2);
    report("вкладка 1: возврат фокуса", focus);
    console.log(
      `\n=== ИТОГ две вкладки ===\n` +
        `вкладка 1 (вход): ${tab1.total} запросов / ${tab1.bytes} Б; ` +
        `вкладка 2 (полный проход): ${tab2.total} запросов / ${tab2.bytes} Б; ` +
        `вкладка 1 после возврата фокуса: ${focus.total} запросов / ${focus.bytes} Б; ` +
        `сумма за замер: ${tab1.total + tab2.total + focus.total} запросов / ` +
        `${tab1.bytes + tab2.bytes + focus.bytes} Б`,
    );
    await page2.close();
  });
});
