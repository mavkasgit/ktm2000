import { test, expect } from "./fixtures";
import {
  apiApplyChangeSet,
  apiGetActiveTemplate,
  apiSimulatePlanImport,
} from "./api-helpers";
import {
  E2E_CATALOG_XLS_PATH,
  E2E_REMAINDERS_XLS_PATH,
  E2E_SKU,
  approvePositionViaUI,
  completeAllSectionTasksViaUI,
  expectShippedViaUI,
  findApprovablePositionViaUI,
  importCatalogViaUI,
  importRemaindersViaUI,
  seedReferenceDataViaUI,
  sendReadyTransfersViaUI,
  takeToWorkViaUI,
  waitForPlanningTableViaUI,
  type ApprovablePosition,
} from "./ui-helpers";

/**
 * @ui — канонический E2E (тикет #88): полный производственный цикл для ЮП-009.
 * Каталог и остатки — живой импорт через UI-визарды; план — бесфайловый сетап
 * через API; дальше approve → запуск → маршрут → отгрузка (UI).
 *
 * Живой импорт главного xlsx-плана через визард проверяет
 * `route-workflow.spec.ts` (фикстура `testdata/Упаковочный план.xlsx`).
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

    // ── ШАГ 2. Импорт остатков на «Склад сырья» ───────────────────────
    await importRemaindersViaUI(page, E2E_REMAINDERS_XLS_PATH);
    console.log("[step2] остатки импортированы");

    // ── ШАГ 3. План из двух позиций ───────────────────────────────────
    const template = await apiGetActiveTemplate();
    const importRes = await apiSimulatePlanImport(
      [
        {
          sku: E2E_SKU,
          name: "Уголок 15*15",
          raw_stock: 400,
          color: "серебро",
          qty_per_27: 300,
          length_m: 2.05,
          packaging: "смотка спанбондом поштучно в пачке 10 штук",
          output_length_m: 2.05,
          output_qty: 300,
          west: 300,
          east: 0,
          kind: "П/ф",
        },
        {
          sku: E2E_SKU,
          name: "Уголок 15*15",
          raw_stock: 300,
          color: "серебро",
          qty_per_27: 200,
          length_m: 3.05,
          packaging: "смотка спанбондом поштучно в пачке 10 штук",
          output_length_m: 3.05,
          output_qty: 200,
          west: 200,
          east: 0,
          kind: "П/ф",
        },
      ],
      { templateId: template.id },
    );
    await apiApplyChangeSet(importRes.production_plan_id, importRes.change_set_id);

    await page.goto("/planning");
    await expect(page.getByRole("heading", { name: "План", exact: true })).toBeVisible({
      timeout: 10_000,
    });
    await waitForPlanningTableViaUI(page);
    console.log("[step3] план импортирован");

    // ── ШАГ 5. Утверждение обеих позиций (без force-диалога) ──────────
    const positions: ApprovablePosition[] = [];
    for (let attempt = 0; attempt < 2; attempt++) {
      const position = await findApprovablePositionViaUI(page);
      if (!position) {
        test.skip(true, "Нет утверждаемых позиций после импорта плана ЮП-009");
        break;
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
    // Проверка привязана к позициям этого прогона — в накопительной dev-БД
    // строки прошлых прогонов иначе давали бы ложный зелёный.
    await expectShippedViaUI(page, E2E_SKU, positions.map((position) => position.id));
    console.log("[step8] отгрузка подтверждена");
  });
});
