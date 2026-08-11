import { test, expect } from "./fixtures";
import {
  E2E_CATALOG_XLS_PATH,
  E2E_PLAN_XLS_PATH,
  E2E_REMAINDERS_XLS_PATH,
  E2E_SKU,
  approvePositionViaUI,
  completeAllSectionTasksViaUI,
  ensureStandardTechcardsViaUI,
  expectShippedViaUI,
  findApprovablePositionViaUI,
  importCatalogViaUI,
  importRemaindersViaUI,
  seedReferenceDataViaUI,
  sendReadyTransfersViaUI,
  takeToWorkViaUI,
  uploadTestFileViaUI,
  waitForPlanningTableViaUI,
} from "./ui-helpers";

/**
 * @ui — канонический E2E (тикет #88): полный производственный цикл для ЮП-009.
 * Каталог через Excel → остатки → план → утверждение → запуск → маршрут → отгрузка.
 * Только UI, без прямых fetch к бизнес-API.
 */
test.describe("@ui Полный цикл производства (ЮП-009)", () => {
  test.beforeEach(async ({ page, loginAsAdmin }) => {
    await loginAsAdmin();
    await seedReferenceDataViaUI(page);
  });

  test("каталог → остатки → план → approve → запуск → маршрут → отгрузка", async ({ page }) => {
    test.slow();

    page.on("response", async (response) => {
      const url = response.url();
      if (url.includes("/api/") && response.status() >= 400) {
        console.log(`[API ERROR] ${response.status()} ${url}`);
        try {
          console.log("Error body:", JSON.stringify(await response.json()));
        } catch (e) {
          console.log("Error text:", await response.text());
        }
      }
    });

    // ── ШАГ 1. Импорт каталога ЮП-009 ────────────────────────────────
    await importCatalogViaUI(page, E2E_CATALOG_XLS_PATH);
    console.log("[step1] каталог импортирован");

    // ── ШАГ 2. Массовое создание техкарты ─────────────────────────────
    await ensureStandardTechcardsViaUI(page, [E2E_SKU]);
    console.log("[step2] техкарта создана");

    // ── ШАГ 3. Импорт остатков на «Склад сырья» ───────────────────────
    await importRemaindersViaUI(page, E2E_REMAINDERS_XLS_PATH);
    console.log("[step3] остатки импортированы");

    // ── ШАГ 4. Импорт плана из двух позиций ───────────────────────────
    await page.goto("/planning");
    await expect(page.getByRole("heading", { name: "План", exact: true })).toBeVisible({
      timeout: 10_000,
    });
    await uploadTestFileViaUI(page, E2E_PLAN_XLS_PATH);
    await waitForPlanningTableViaUI(page);
    console.log("[step4] план импортирован");

    // ── ШАГ 5. Утверждение обеих позиций (без force-диалога) ──────────
    const positions = [];
    for (let attempt = 0; attempt < 2; attempt++) {
      const position = await findApprovablePositionViaUI(page);
      if (!position) {
        test.skip(true, "Нет утверждаемых позиций после импорта плана ЮП-009");
      }
      positions.push(position);
      await approvePositionViaUI(page, position);
      console.log(`[step5] позиция #${position.id} утверждена`);
    }

    // ── ШАГ 6. Запуск в работу обеих позиций на /execution ───────────
    for (const position of positions) {
      await takeToWorkViaUI(page, position);
      console.log(`[step6] позиция #${position.id} запущена`);
    }

    // ── ШАГ 7. Маршрут: передачи + задачи на производственных участках ─
    // Динамический проход: после каждой операции на /transfers появляются новые
    // готовые передачи (на следующие участки) — отправляем их теми же кликами,
    // а затем завершаем завершаемые задачи на участках. Повторяем, пока есть
    // что передать или завершить (маршрут доходит до «Отправлено»).
    for (let round = 0; round < 30; round++) {
      const sent = await sendReadyTransfersViaUI(page, E2E_SKU);
      const completed = await completeAllSectionTasksViaUI(page, E2E_SKU);
      console.log(`[step7] раунд ${round}: sent=${sent} completed=${completed}`);
      if (sent === 0 && completed === 0) break;
    }
    console.log("[step7] маршрут пройден");

    // ── ШАГ 8. Финальный контроль: материал доехал до «Отправлено» ─────────
    await expectShippedViaUI(page, E2E_SKU);
    console.log("[step8] отгрузка подтверждена");
  });
});
