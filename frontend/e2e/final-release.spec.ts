import { test, expect } from "./fixtures";
import {
  apiAddRemainder,
  apiAddRouteStep,
  apiAccessTokenFromPage,
  apiCreateBareProduct,
  apiCreateRoute,
  apiGetSectionByCode,
  apiResetAll,
  apiRunDemoFullRoute,
  apiSeedData,
  apiGetOrCreateTechcard,
} from "./api-helpers";

/**
 * @smoke — тикет #96: финальный выпуск кнопкой «Отправить» на странице передач.
 *
 * Сид-роут финализирует на SHIPPED (складская секция), поэтому спека создаёт
 * кастомный роут RAW_STOCK → PACKING(финальная production-стадия) через API,
 * прогоняет его через /api/demo/test-runs/full-route (задачи завершены, но
 * финальный выпуск НЕ выполнен), затем проверяет в UI:
 *
 * 1. В «Готово к передаче» появляется финальная строка (is_final) с кнопкой
 *    «Отправить» (а не «Передать»).
 * 2. Клик «Отправить» уводит строку из списка (releasable → 0).
 *
 * Требует запущенного dev-окружения: `npm run dev` из корня проекта.
 */

test.describe("@smoke Финальный выпуск кнопкой «Отправить» (#96)", () => {
  test.beforeEach(async () => {
    await apiResetAll();
    await apiSeedData();
  });

  test("финальная production-строка выпускается через «Отправить»", async ({
    authenticatedPage,
  }) => {
    test.slow();

    const token = await apiAccessTokenFromPage(authenticatedPage);
    expect(token).toBeTruthy();

    // 1. Свежий продукт без lengths (как в demo-фикстурах) + техкарта.
    const sku = `E2E-FINAL-${Date.now()}`;
    const product = await apiCreateBareProduct(sku);
    const techcard = await apiGetOrCreateTechcard(product);

    // 2. Кастомный роут: RAW_STOCK (транзит) → PACKING (production, final).
    const raw = await apiGetSectionByCode("RAW_STOCK");
    const packing = await apiGetSectionByCode("PACKING");
    const route = await apiCreateRoute(`E2E-FINAL-RELEASE-${Date.now()}`);
    await apiAddRouteStep(route.id, {
      sequence: 1,
      section_id: raw.id,
      operation_code: null,
      operation_name: "Выдача сырья",
      is_final: false,
      stage_kind: "transit",
      storage_section_id: raw.id,
    });
    await apiAddRouteStep(route.id, {
      sequence: 2,
      section_id: packing.id,
      operation_code: null,
      operation_name: "Упаковка",
      is_final: true,
    });

    // 2a. Остаток сырья на RAW_STOCK (длина 2,7 м) — иначе выпуск из сырья невозможен.
    await apiAddRemainder(
      product.id,
      raw.id,
      100,
      "E2E final-release: начальный остаток сырья",
      { length_mm: 2700 },
    );

    // 3. Прогон роута до конца: задача на PACKING завершена, но не выпущена.
    const run = await apiRunDemoFullRoute(token, {
      initial_quantity: "40",
      route_id: route.id,
      techcard_id: techcard.id,
      run_id: `e2e-final-release-${Date.now()}`,
    });
    expect(run.stopped_at_stage).toBe("completed");
    const packingStage = run.stage_results.find(
      (s: { section_code: string }) => s.section_code === "PACKING",
    );
    expect(packingStage).toBeTruthy();
    expect(Number(packingStage.good_qty)).toBeGreaterThan(0);

    // 4. UI: /transfers — строка PACKING финальная, кнопка «Отправить».
    await authenticatedPage.goto("/transfers");
    await expect(
      authenticatedPage.getByRole("heading", { name: "Передачи между ГХП" }),
    ).toBeVisible({ timeout: 10_000 });

    const readyCard = authenticatedPage
      .locator("div", { hasText: "Готово к передаче" })
      .filter({ has: authenticatedPage.locator("table") })
      .filter({ hasNotText: "Журнал передач" })
      .first();
    const readyRow = readyCard.locator("tr", { hasText: sku }).first();
    await expect(readyRow).toBeVisible({ timeout: 15_000 });

    // Финальная строка: бейдж «Финальный», кнопка «Отправить», без «Передать».
    await expect(readyRow.locator("td").filter({ hasText: "Финальный" })).toBeVisible({
      timeout: 5_000,
    });
    const sendBtn = readyRow.getByRole("button", { name: "Отправить" });
    await expect(sendBtn).toBeVisible({ timeout: 5_000 });
    await expect(readyRow.getByRole("button", { name: "Передать" })).toHaveCount(0);

    // 5. Клик «Отправить» — строка уходит из «Готово к передаче».
    await sendBtn.click();
    await expect(readyRow).not.toBeVisible({ timeout: 15_000 });
  });
});
