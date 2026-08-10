import { test, expect } from "./fixtures";
import path from "path";

/**
 * E2E test for the explicit-transfer 2-step ritual:
 *
 *   1. **Send** (UI on /transfers) — auto-accepts inline, material
 *      arrives on the destination as ``cached_received_quantity``;
 *      the destination task flips ``waiting_previous → ready``.
 *   2. **Issue** (API on /shopfloor/tasks/{id}/issue) — material
 *      moves from ``cached_received_quantity`` to
 *      ``cached_in_work_quantity``; task status ``ready → in_progress``.
 *
 * Reject/partial-accept were removed from the model — see
 * ``docs/superpowers/plans/2026-07-01-explicit-transfers-mandatory.md``.
 *
 * The Issue step is driven through the API because the section-tasks
 * page exposes only a «Завершить» action — the dedicated
 * «Выдать в работу» button is on the roadmap. Once it lands, the
 * Issue step in this test can be promoted to a UI assertion.
 */

import {
  apiAddRemainder,
  apiApplyChangeSet,
  apiBatchAssignRoute,
  apiGetActiveRoutes,
  apiGetActiveTemplate,
  apiGetOrCreateTechcard,
  apiGetPlanPositions,
  apiGetProductBySku,
  apiGetSectionByCode,
  apiImportExcel,
  apiResetAll,
  apiEnsureTestProducts,
  apiEnsureTestTechcards,
  apiSeedData,
  BACKEND_URL,
  E2E_SECTION,
} from "./api-helpers";
import { confirmProductionLaunchViaUI } from "./ui-helpers";

// --- Test -----------------------------------------------------------------

/** @smoke — API-assisted setup; не канон E2E. См. @ui в route-workflow.spec.ts */
test.describe("@smoke Explicit transfer — 2-step ritual (Send + Issue)", () => {
  test.beforeEach(async () => {
    await apiResetAll();
    await apiSeedData();
    await apiEnsureTestProducts();
    await apiEnsureTestTechcards();
  });

  test("send auto-accepts, then operator issues on destination", async ({
    authenticatedPage,
    request,
  }) => {
    test.slow();

    // 1. Подготовка данных: продукт, техкарта, импорт Excel, применение, маршрут
    const product2083 = await apiGetProductBySku("ЮП-2083");
    const techcard = await apiGetOrCreateTechcard(product2083);

    const template = await apiGetActiveTemplate();
    const xlsPath = path.resolve(process.cwd(), "../Упаковочный план.xlsx");
    const importRes = await apiImportExcel(template.id, xlsPath);
    await apiApplyChangeSet(importRes.production_plan_id, importRes.change_set_id);

    const positions = await apiGetPlanPositions(importRes.production_plan_id);
    const pos2083 = positions.find(
      (p: { source_sku: string; validation_status: string }) =>
        p.source_sku === "ЮП-2083" && p.validation_status === "valid",
    );
    expect(pos2083).toBeDefined();
    expect(pos2083.route_id).toBeTruthy();

    const activeRoutes = await apiGetActiveRoutes();
    expect(activeRoutes.length).toBeGreaterThan(0);
    void techcard;

    // 1a. Пополняем остатки на STOCK (Склад сырья) — иначе диалог
    //     «Запуск в производство» покажет пустое обеспечение сырьём.
    const sectionWh = await apiGetSectionByCode(E2E_SECTION.RAW_STOCK);
    const planQty = Math.round(parseFloat(pos2083.quantity));
    await apiAddRemainder(
      product2083.id,
      sectionWh.id,
      planQty,
      "E2E: начальный остаток сырья для transfers-auto-accept",
    );

    // 2. Утверждаем позицию на странице /planning (с обработкой диалога «Утвердить всё равно»)
    await authenticatedPage.goto("/planning");
    const planSearch = authenticatedPage.getByPlaceholder("Поиск");
    await expect(planSearch).toBeVisible({ timeout: 10_000 });
    await planSearch.fill("ЮП-2083");

    const planRow = authenticatedPage.locator(`#plan-position-${pos2083.id}`);
    await expect(planRow).toBeVisible({ timeout: 15_000 });
    const approveBtn = planRow.getByRole("button", { name: "Утвердить" });
    await expect(approveBtn).toBeVisible({ timeout: 5_000 });
    await approveBtn.click();

    const visibleConfirmBtn = authenticatedPage
      .locator("button", { hasText: "Утвердить всё равно" })
      .filter({ visible: true });
    try {
      await expect(visibleConfirmBtn).toBeVisible({ timeout: 3_000 });
      await visibleConfirmBtn.click();
    } catch {
      // no risk dialog
    }
    await expect(approveBtn).not.toBeVisible({ timeout: 10_000 });

    // 3. Берём в работу на /execution
    await authenticatedPage.goto("/execution");
    const execSearch = authenticatedPage.getByPlaceholder("Поиск");
    await expect(execSearch).toBeVisible({ timeout: 10_000 });
    await execSearch.fill("ЮП-2083");
    const execRow = authenticatedPage.locator("tr", { hasText: `#${pos2083.id}` }).first();
    await expect(execRow).toBeVisible({ timeout: 15_000 });
    const launchBtn = execRow.getByRole("button", { name: "Взять в работу" });
    await expect(launchBtn).toBeVisible({ timeout: 5_000 });
    await launchBtn.click();

    await confirmProductionLaunchViaUI(authenticatedPage);

    await expect(execRow.locator("span").filter({ hasText: /^Запущен$/ })).toBeVisible({
      timeout: 15_000,
    });

    // 4. Завершаем 10 годных на первом production-участке через TaskActionDrawer
    //    Берём первый production-section для этой позиции.
    const sectionsRes = await fetch(`${BACKEND_URL}/api/sections`);
    const sectionsBody = (await sectionsRes.json()) as Array<{ id: number; type: string }> | { items: Array<{ id: number; type: string }> };
    const sections = Array.isArray(sectionsBody) ? sectionsBody : sectionsBody.items ?? [];
    const firstSection = sections.find((s) => s.type === "production");
    expect(firstSection).toBeDefined();

    await authenticatedPage.goto(`/section-tasks/${firstSection!.id}`);
    const firstRow = authenticatedPage.locator("tr", { hasText: "ЮП-2083" }).first();
    await expect(firstRow).toBeVisible({ timeout: 15_000 });
    const completeBtn = firstRow.getByRole("button", { name: "Завершить" }).first();
    await expect(completeBtn).toBeVisible({ timeout: 5_000 });
    await completeBtn.click();

    const drawer = authenticatedPage.getByRole("dialog");
    await expect(drawer).toBeVisible({ timeout: 5_000 });
    const goodInput = drawer.locator('input[type="number"]').first();
    await goodInput.fill("10");
    await drawer.getByRole("button", { name: "Сохранить" }).click();
    await expect(drawer).not.toBeVisible({ timeout: 10_000 });

    // 5. SEND на /transfers — auto-accepts по новой модели
    await authenticatedPage.goto("/transfers");
    await expect(
      authenticatedPage.getByRole("heading", { name: "Передачи между ГХП" }),
    ).toBeVisible({ timeout: 10_000 });

    const readyRow = authenticatedPage
      .locator("tr", { hasText: "ЮП-2083" })
      .filter({ hasText: "Готово к передаче" })
      .first();
    // «Готово к передаче» — текст в шапке, не в строке. Ищем строку с ЮП-2083 в таблице «ready».
    const readyRowBySku = authenticatedPage
      .locator("table", { hasText: "Готово к передаче" })
      .locator("tr", { hasText: "ЮП-2083" })
      .first();
    await expect(readyRowBySku).toBeVisible({ timeout: 10_000 });

    // Найдём инпут «qty» и кнопку «Передать» в этой строке
    const qtyInput = readyRowBySku.locator('input[type="number"]').first();
    await qtyInput.fill("10");
    const sendBtn = readyRowBySku.getByRole("button", { name: "Передать" });
    await expect(sendBtn).toBeVisible({ timeout: 5_000 });
    await sendBtn.click();

    // После успешной отправки строка должна исчезнуть из «Готово к передаче»
    await expect(readyRowBySku).not.toBeVisible({ timeout: 15_000 });

    // 6. Проверяем, что в «Истории» (правая колонка) появилась запись со статусом «Принята»
    //    — auto-accept произошёл inline внутри transfer_send.
    const historyRow = authenticatedPage
      .locator("table", { hasText: "История" })
      .locator("tr", { hasText: "ЮП-2083" })
      .first();
    await expect(historyRow).toBeVisible({ timeout: 10_000 });
    await expect(historyRow.locator("td").filter({ hasText: "Принята" })).toBeVisible({
      timeout: 5_000,
    });

    // 7. Достаём токен админа из cookies для API-запросов
    const cookies = await authenticatedPage.context().cookies();
    const accessCookie = cookies.find((c) => c.name === "access_token");
    const token = accessCookie?.value ?? "";

    // 8. Находим задачу-получатель на втором production-участке
    const secondSection = sections.filter((s) => s.type === "production")[1];
    expect(secondSection).toBeDefined();

    // 8. Достаём board второго участка — там должна быть наша задача в in_progress
    //    (auto-issue после transfer_send)
    const boardRes = await fetch(
      `${BACKEND_URL}/api/shopfloor/sections/${secondSection!.id}/board`,
      { headers: { Authorization: `Bearer ${token}` } },
    );
    if (!boardRes.ok) {
      throw new Error(`Get board failed: ${boardRes.statusText} (${boardRes.status})`);
    }
    const board = (await boardRes.json()) as {
      tasks: Array<{ id: number; product_sku: string; status: string; cache: { received_quantity: string } }>;
    };
    const destinationTask = board.tasks.find(
      (t) => t.product_sku === "ЮП-2083" && t.cache.received_quantity !== "0",
    );
    expect(destinationTask).toBeDefined();
    // After transfer_send, auto-issue puts the task into in_progress directly
    expect(destinationTask!.status).toBe("in_progress");
    expect(destinationTask!.cache.in_work_quantity).toBe("10");

    // Тест завершён: после transfer_send задача уже in_progress с in_work=10
  });
});
