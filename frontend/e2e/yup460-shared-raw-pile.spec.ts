import { test, expect } from "./fixtures";
import {
  BACKEND_URL,
  apiAccessTokenFromPage,
  apiAddRemainder,
  apiApplyChangeSet,
  apiGetActiveTemplate,
  apiGetSectionByCode,
  apiResetAll,
  apiSimulatePlanImport,
  unwrapItems,
} from "./api-helpers";
import { seedReferenceDataViaUI, waitForPlanningTableViaUI } from "./ui-helpers";

/**
 * @ui — ЮП-460 в трёх вариантах делят одну кучу чистого сырья.
 *
 * План из трёх строк одного артикула, различающихся только
 * «Пробивкой/сверловкой»: «окно» (PRESS_WINDOW), «гребенка» (PRESS_COMB)
 * и пусто (без пресса). Сырьё — одна куча чистого (Годный, без операций)
 * 1000 × 2,05 м на «Складе сырья».
 *
 * Регрессия: варианты разъезжались по разным продуктам/кучам, и индикатор
 * свободного остатка показывал, например, «окно — 1000», а «гребенка — 0».
 * Здесь проверяется, что все три позиции видят один и тот же остаток 1000.
 *
 * Сетап — через API без файлов (продукт + остаток), в кадре только действия
 * в UI: проверка каталога, проверка склада, импорт плана через визард
 * (файл генерируется на лету в tmp скриптом ниже) и проверки таблицы плана.
 * Прецедент API-сетапа в @ui — `sawing-multi-length-split.spec.ts`.
 *
 * Требует запущенного dev-окружения: `npm run dev` из корня проекта.
 */

const SKU = "ЮП-460";
const PRODUCT_NAME = "Профиль ЮП-460";
/** Одна куча чистого сырья: количество заготовок. */
const PILE_QTY = 1000;

async function apiJson(token: string, pathname: string, method: "GET" | "POST" = "GET", payload?: unknown) {
  const res = await fetch(`${BACKEND_URL}${pathname}`, {
    method,
    headers: {
      "Content-Type": "application/json",
      Authorization: `Bearer ${token}`,
    },
    body: payload ? JSON.stringify(payload) : undefined,
  });
  if (!res.ok) {
    throw new Error(`${method} ${pathname} failed: ${res.status} ${await res.text()}`);
  }
  return res.json();
}

/** Продукт ЮП-460 через API: если уже есть в накопительной dev-БД — пропускаем создание. */
async function apiEnsureProduct460(token: string): Promise<{ id: number; sku: string }> {
  const list = async () =>
    unwrapItems<{ id: number; sku: string }>(
      await apiJson(token, `/api/products?q=${encodeURIComponent(SKU)}`),
    );
  const existing = (await list()).filter((p) => p.sku === SKU);
  if (existing.length > 0) {
    console.log(`[setup] продукт ${SKU} уже существует (#${existing[0].id}) — пропускаем создание`);
    return existing[0];
  }
  await apiJson(token, "/api/products", "POST", {
    sku: SKU,
    name: PRODUCT_NAME,
    type: "component",
    unit: "pcs",
    is_active: true,
    is_catalog_item: true,
    lengths_mm: [2050, 3050],
    length_mm: 2050,
  });
  const created = (await list()).filter((p) => p.sku === SKU);
  expect(created.length, `продукт ${SKU} не создался`).toBe(1);
  return created[0];
}

/**
 * Сырьевые длины продукта. Продукт может уже существовать в накопительной
 * dev-БД (reset-all справочник сырья не чистит) — подстраиваем план и кучу
 * под его минимальную длину, чтобы вход материализовался точь-в-точь
 * (ADR-0024) без подстановки «ближайшей сверху».
 */
async function apiGetProductLengthsMm(token: string, productId: number): Promise<number[]> {
  const body = await apiJson(token, `/api/products/${productId}`);
  const lengths = Array.isArray(body?.lengths_mm)
    ? body.lengths_mm.map(Number).filter((n: number) => Number.isFinite(n) && n > 0)
    : [];
  return lengths.length > 0 ? lengths : [2050];
}

/** Свободный остаток из текста строки плана («[ЮП-460] · 1000 …»). */
function parseRemainder(rowText: string): number | null {
  const match = rowText.match(/·\s*(\d+)/);
  if (!match) return null;
  const value = Number(match[1]);
  return Number.isFinite(value) ? value : null;
}

test.describe("@ui ЮП-460: окно / гребенка / без пресса делят одну кучу сырья", () => {
  test.beforeEach(async ({ page, loginAsAdmin }) => {
    await loginAsAdmin();
    // API-сетап с токеном страницы (приём из sawing-multi-length-split).
    const token = await apiAccessTokenFromPage(page);
    expect(token).toBeTruthy();
    const originalFetch = globalThis.fetch.bind(globalThis);
    globalThis.fetch = async (input, init) => {
      const headers = new Headers(init?.headers);
      if (!headers.has("Authorization")) headers.set("Authorization", `Bearer ${token}`);
      return originalFetch(input, { ...init, headers });
    };
    // `reset-all` чистит планы, остатки и шаблоны — порядок обязателен:
    // сначала сброс, потом сид справочников.
    await apiResetAll();
    await seedReferenceDataViaUI(page);
  });

  test("каталог → склад → план из 3 строк: у всех остаток 1000 из одной кучи", async ({
    page,
  }) => {
    test.slow();
    test.setTimeout(300_000);

    page.on("response", async (response) => {
      if (response.status() < 400 || !response.url().includes("/api/")) return;
      const body = await response.text().catch(() => "");
      console.log(
        `[api ${response.status()}] ${response.request().method()} ${response.url()} → ${body.slice(0, 400)}`,
      );
    });

    // ── API-сетап: продукт + одна куча чистого ──────────────────────────
    const token = await apiAccessTokenFromPage(page);
    const product = await apiEnsureProduct460(token);
    const lengthsMm = await apiGetProductLengthsMm(token, product.id);
    const pileLengthMm = Math.min(...lengthsMm);
    const pileLengthM = Math.round((pileLengthMm / 1000) * 100) / 100;
    const raw = await apiGetSectionByCode("RAW_STOCK");
    await apiAddRemainder(
      product.id,
      raw.id,
      PILE_QTY,
      `E2E ЮП-460: одна куча чистого ${pileLengthMm}мм`,
      { length_mm: pileLengthMm },
    );
    console.log(`[setup] продукт #${product.id}, куча ${PILE_QTY} × ${pileLengthMm}мм`);

    // ── ШАГ 1. Каталог в UI: ЮП-460 на месте ──────────────────────────
    await page.goto("/references/raw-materials");
    await expect(page.getByRole("heading", { name: "Справочник сырья" })).toBeVisible({
      timeout: 10_000,
    });
    await page.getByPlaceholder("Поиск").fill(SKU);
    await page.waitForTimeout(800);
    const catalogRow = page.locator("tr", { hasText: SKU }).first();
    await expect(catalogRow, "ЮП-460 не найден в справочнике сырья").toBeVisible({
      timeout: 10_000,
    });
    console.log("[step1] каталог в UI корректен");

    // ── ШАГ 2. Склад в UI: одна куча 1000, Годный ─────────────────────
    await page.goto("/spg");
    await expect(page.getByRole("button", { name: "Импорт из Excel" })).toBeVisible({
      timeout: 10_000,
    });
    await page.getByPlaceholder("Глобальный поиск по артикулу или названию...").fill(SKU);
    const pileRow = page.locator("tr", { hasText: SKU }).first();
    await expect(pileRow, "куча ЮП-460 не видна на складе").toBeVisible({ timeout: 15_000 });
    const pileText = ((await pileRow.innerText()) ?? "").replace(/\s+/g, " ").trim();
    expect(pileText, `куча должна быть ${PILE_QTY} шт: ${pileText}`).toContain(String(PILE_QTY));
    expect(pileText, `куча должна быть годной: ${pileText}`).toContain("Годный");
    console.log(`[step2] склад в UI корректен: ${pileText}`);

    // ── ШАГ 3. План: бесфайловый импорт 3 строк ────────────────────────
    // Три строки одного артикула, различающихся «Пробивкой/сверловкой»:
    // окно / гребенка / пусто. xlsx не храним — строки уходят в API.
    const template = await apiGetActiveTemplate();
    const importRes = await apiSimulatePlanImport(
      (["окно", "гребенка", null] as const).map((operation) => ({
        sku: SKU,
        name: PRODUCT_NAME,
        raw_stock: PILE_QTY,
        color: "серебро",
        qty_per_27: 100,
        length_m: pileLengthM,
        operation,
        packaging: "смотка спанбондом поштучно в пачке 10 штук",
        output_length_m: pileLengthM,
        output_qty: 100,
        west: 100,
        east: 0,
        kind: "П/ф",
      })),
      { templateId: template.id },
    );
    await apiApplyChangeSet(importRes.production_plan_id, importRes.change_set_id);

    await page.goto("/planning");
    await expect(page.getByRole("heading", { name: "План", exact: true })).toBeVisible({
      timeout: 10_000,
    });
    await waitForPlanningTableViaUI(page);
    const rows = page.locator('[id^="plan-position-"]');
    await expect(rows, "в плане должно быть ровно 3 позиции ЮП-460").toHaveCount(3);
    console.log("[step3] план импортирован (3 строки)");

    // ── ШАГ 4. Общая куча: у всех трёх остаток 1000 ───────────────────
    const remainders: number[] = [];
    const rowTexts: string[] = [];
    for (let i = 0; i < 3; i++) {
      const text = ((await rows.nth(i).innerText()) ?? "").replace(/\s+/g, " ").trim();
      rowTexts.push(text);
      expect(text, `строка ${i}: неожиданный артикул`).toContain(SKU);
      expect(text, `строка ${i}: маршрут не назначен`).not.toContain("Не назначен");
      const remainder = parseRemainder(text);
      expect(remainder, `строка ${i}: индикатор остатка не читается: ${text}`).not.toBeNull();
      remainders.push(remainder!);
    }
    for (const [i, value] of remainders.entries()) {
      expect(
        value,
        `позиция ${i} видит ${value}, а не общую кучу ${PILE_QTY}: ${rowTexts[i]}`,
      ).toBe(PILE_QTY);
    }
    console.log(`[step4] остатки всех позиций: ${remainders.join(" / ")}`);

    // ── ШАГ 5. Три разных варианта, а не три копии ─────────────────────
    const joined = rowTexts.join("\n");
    expect(joined, "нет варианта «окно»").toMatch(/окн/i);
    expect(joined, "нет варианта «гребенка»").toMatch(/греб/i);
    const withoutPress = rowTexts.filter((t) => !/окн/i.test(t) && !/греб/i.test(t));
    expect(withoutPress.length, "нет варианта без пресса").toBe(1);
    console.log("[step5] варианты: окно + гребенка + без пресса");
  });
});
