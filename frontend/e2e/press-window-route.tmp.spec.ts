import { test, expect } from "./fixtures";
import path from "path";
import { fileURLToPath } from "url";
import { apiResetAll } from "./api-helpers";
import {
  approvePositionViaUI,
  completeAllSectionTasksViaUI,
  expectShippedViaUI,
  findApprovablePositionViaUI,
  importCatalogViaUI,
  importRemaindersViaUI,
  seedReferenceDataViaUI,
  sendReadyTransfersViaUI,
  takeToWorkViaUI,
  transferRouteChainViaUI,
  uploadTestFileViaUI,
  waitForPlanningTableViaUI,
} from "./ui-helpers";

const __dirname = path.dirname(fileURLToPath(import.meta.url));

/**
 * ВРЕМЕННАЯ спека (тег `@tmp`) — разовый прогон, не часть регулярного набора.
 *
 * В обычных прогонах НЕ участвует: тег `@tmp` не совпадает ни с `@ui`, ни с
 * `@smoke`, а проект `tmp` подключается в `playwright.config.ts` только при
 * `E2E_TMP=1`. Запуск разово:
 *
 *   E2E_TMP=1 npx playwright test --project=tmp e2e/press-window-route.tmp.spec.ts
 *
 * Удаляется вместе с фикстурами `Каталог пресс E2E.xlsx`,
 * `Склад импорта остатков пресс E2E.xlsx`, `Упаковочный план пресс E2E.xlsx`.
 */

/**
 * @tmp — ОДНА строка плана, артикул с операцией «окно» (участок «Пресс»).
 *
 * Тот же сквозной проход, что и в `single-line-cycle.spec.ts`, но план содержит
 * «Пробивка/сверловка» = «окно»: правило `press_section` (селектор маршрута,
 * профиль `packaging_map_rp`) требует PRESSING, исключает DRILLING, а
 * `press_types` ставит операцию PRESS_WINDOW. Значит, первый производственный
 * участок маршрута — «Пресс», и тест это проверяет явно.
 */
const PRESS_SKU = "ЮП-4610";
const CATALOG_XLS_PATH = path.resolve(__dirname, "../../Каталог пресс E2E.xlsx");
const REMAINDERS_XLS_PATH = path.resolve(
  __dirname,
  "../../Склад импорта остатков пресс E2E.xlsx",
);
const PLAN_XLS_PATH = path.resolve(__dirname, "../../Упаковочный план пресс E2E.xlsx");

test.describe("@tmp [временная] Окно с участком пресса: сквозной маршрут", () => {
  test.beforeEach(async ({ page, loginAsAdmin }) => {
    await loginAsAdmin();
    // `reset-all` чистит и справочники импорта (TRUNCATE ... import_templates),
    // поэтому порядок обязателен: сначала сброс, потом сид шаблонов.
    await apiResetAll();
    await seedReferenceDataViaUI(page);
  });

  test("запуск → передачи ↔ участки по кругу → Пресс в маршруте → материал в «Отправлено»", async ({
    page,
  }) => {
    test.slow();

    page.on("response", async (response) => {
      if (response.status() < 400 || !response.url().includes("/api/")) return;
      const body = await response.text().catch(() => "");
      console.log(
        `[api ${response.status()}] ${response.request().method()} ${response.url()} → ${body.slice(0, 400)}`,
      );
    });

    // ── ШАГ 1. Каталог ─────────────────────────────────────────────────────
    await importCatalogViaUI(page, CATALOG_XLS_PATH);
    console.log("[step1] каталог импортирован");

    // ── ШАГ 2. Остатки на «Склад сырья» ────────────────────────────────────
    await importRemaindersViaUI(page, REMAINDERS_XLS_PATH);
    console.log("[step2] остатки импортированы");

    // ── ШАГ 3. План из ОДНОЙ строки с операцией «окно» ─────────────────────
    await page.goto("/planning");
    await expect(page.getByRole("heading", { name: "План", exact: true })).toBeVisible({
      timeout: 10_000,
    });
    await uploadTestFileViaUI(page, PLAN_XLS_PATH);
    await waitForPlanningTableViaUI(page);
    await expect(page.locator('[id^="plan-position-"]')).toHaveCount(1);
    console.log("[step3] план импортирован (1 строка, «окно»)");

    // ── ШАГ 4. Утверждение единственной позиции ────────────────────────────
    const position = await findApprovablePositionViaUI(page);
    expect(position, "в плане нет строки для утверждения").not.toBeNull();
    await approvePositionViaUI(page, position!);
    expect(position!.sku, "в плане неожиданный артикул").toContain(PRESS_SKU);
    console.log(`[step4] позиция #${position!.id} утверждена`);

    // ── ШАГ 5. Запуск в работу на «Контроль выполнения» ────────────────────
    await takeToWorkViaUI(page, position!);
    console.log(`[step5] позиция #${position!.id} запущена`);

    // ── ШАГ 6. Маршрут: передачи ↔ участки ────────────────────────────────
    let transferred = 0;
    let idleRounds = 0;
    let routeChain: string[] = [];
    for (let round = 0; round < 40; round++) {
      const sent = await sendReadyTransfersViaUI(page, PRESS_SKU);
      transferred += sent;

      routeChain = await transferRouteChainViaUI(page, PRESS_SKU, position!.id);
      expect(routeChain, `раунд ${round}: в журнале нет передач позиции`).not.toHaveLength(0);

      const currentSection = routeChain[routeChain.length - 1];
      const completed = await completeAllSectionTasksViaUI(page, PRESS_SKU, [currentSection]);
      console.log(
        `[step6] раунд ${round}: передано ${sent}, путь до «${currentSection}» (шагов ${routeChain.length}), завершено ${completed}`,
      );

      if (sent === 0 && completed === 0) {
        if (++idleRounds >= 2) break;
      } else {
        idleRounds = 0;
      }
    }
    expect(transferred, "маршрут не прошёл ни одной передачи").toBeGreaterThan(0);
    console.log(`[step6] маршрут: Склад сырья → ${routeChain.join(" → ")}`);

    // Главная проверка этой спеки: «окно» в плане провело позицию через Пресс.
    expect(routeChain, "маршрут не прошёл через участок «Пресс»").toContain("Пресс");

    // ── ШАГ 7. Материал доехал до «Отправлено» ─────────────────────────────
    await expectShippedViaUI(page, PRESS_SKU, [position!.id]);
    console.log("[step7] отгрузка подтверждена");
  });
});
