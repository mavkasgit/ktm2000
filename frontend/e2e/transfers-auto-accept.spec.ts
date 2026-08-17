import { test, expect } from "./fixtures";
import path from "path";

/**
 * E2E test for the explicit-transfer ritual under the auto-issue model:
 *
 *   1. **Send** (UI on /transfers) — auto-accepts inline: material arrives
 *      on the destination, the destination task flips
 *      `waiting_previous → ready → in_progress` and the received material
 *      is immediately issued to work (`issued == received`), because the
 *      section-tasks page has no dedicated «Выдать в работу» button.
 *   2. The spec sends raw stock from the storage stage (ready-row in
 *      «Готово к передаче») onto the first production stage: the receiving
 *      stage's board must then show the task `in_progress` with
 *      `received == issued == 10`. The destination is resolved from the
 *      ready API (`next_section_id`), not from route-stage kinds.
 *
 * Reject/partial-accept were removed from the model — see
 * ``docs/superpowers/plans/2026-07-01-explicit-transfers-mandatory.md``.
 */

import {
  apiAccessTokenFromPage,
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
  unwrapItems,
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
    //     Габарит обязателен: складская ready-строка (`compute_stock_section_transferable`)
    //     фильтрует StockBalance по размеру плана ({length_mm:2700} для ЮП-2083),
    //     безразмерный остаток (dimensions=None) дал бы physical_stock=0 и строку бы
    //     скрыл — передача «не сработала бы» (сырьё не видно к отправке).
    const sectionWh = await apiGetSectionByCode(E2E_SECTION.RAW_STOCK);
    const planQty = Math.round(parseFloat(pos2083.quantity));
    await apiAddRemainder(
      product2083.id,
      sectionWh.id,
      planQty,
      "E2E: начальный остаток сырья для transfers-auto-accept",
      { length_mm: 2700 },
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

    // Достаём токен админа для API-запросов (localStorage ktm2000_token).
    const userToken = await apiAccessTokenFromPage(authenticatedPage);

    // 4. SEND на /transfers — auto-accepts по новой модели
    await authenticatedPage.goto("/transfers");
    await expect(
      authenticatedPage.getByRole("heading", { name: "Передачи между ГХП" }),
    ).toBeVisible({ timeout: 10_000 });

    // «Готово к передаче» и «Журнал передач» — две таблицы. Различаем по
    // колонке-признаку: ready имеет «К передаче», журнал — «Статус».
    // (hasText на div матчит и родительский контейнер страницы — нельзя.)
    const readyTable = authenticatedPage
      .locator("table")
      .filter({ has: authenticatedPage.getByRole("columnheader").filter({ hasText: "К передаче" }) })
      .first();
    const journalTable = authenticatedPage
      .locator("table")
      .filter({ has: authenticatedPage.getByRole("columnheader").filter({ hasText: "Статус" }) })
      .first();
    const readyRowBySku = readyTable.locator("tr", { hasText: "ЮП-2083" }).first();
    await expect(readyRowBySku).toBeVisible({ timeout: 10_000 });

    // Найдём инпут «qty» и кнопку «Передать» в этой строке
    const qtyInput = readyRowBySku.locator('input[type="number"]').first();
    await qtyInput.fill("10");
    const sendBtn = readyRowBySku.getByRole("button", { name: "Передать" });
    await expect(sendBtn).toBeVisible({ timeout: 5_000 });
    await sendBtn.click();

    // После успешной отправки строка остаётся (отправлено 10 из planQty),
    // но доступное количество уменьшилось: planQty − 10.
    const qtyAfter = readyTable.locator("tr", { hasText: "ЮП-2083" }).locator('input[type="number"]').first();
    await expect(qtyAfter).toHaveValue(String(planQty - 10), { timeout: 15_000 });

    // 5. Проверяем, что в «Журнале передач» появилась запись со статусом «Принята»
    //    — auto-accept произошёл inline внутри transfer_send.
    const historyRow = journalTable.locator("tr", { hasText: "ЮП-2083" }).first();
    await expect(historyRow).toBeVisible({ timeout: 15_000 });
    await expect(historyRow.locator("td").filter({ hasText: "Принята" })).toBeVisible({
      timeout: 10_000,
    });

    // 6. Цель передачи берём из ready-API: после отправки складская строка
    //    остаётся (planQty−10) и несёт next_section_id получателя.
    const readyAfter = await fetch(`${BACKEND_URL}/api/transfers/ready`, {
      headers: { Authorization: `Bearer ${userToken}` },
    }).then((r) => r.json());
    const readyRows = unwrapItems<{ product_sku?: string; next_section_id?: number | null }>(readyAfter);
    const targetRow = readyRows.find(
      (r) => String(r.product_sku ?? "").includes("ЮП-2083") && r.next_section_id != null,
    );
    expect(targetRow).toBeDefined();

    // 7. Достаём board участка-получателя — там должна быть наша задача
    //    в in_progress (auto-issue после transfer_send).
    const boardRes = await fetch(
      `${BACKEND_URL}/api/shopfloor/sections/${targetRow!.next_section_id}/board`,
      { headers: { Authorization: `Bearer ${userToken}` } },
    );
    if (!boardRes.ok) {
      throw new Error(`Get board failed: ${boardRes.statusText} (${boardRes.status})`);
    }
    const board = (await boardRes.json()) as {
      tasks: Array<{
        id: number;
        product_sku: string;
        status: string;
        cache: { received_quantity: string; issued_quantity: string };
      }>;
    };
    const destinationTask = board.tasks.find(
      (t) => t.product_sku === "ЮП-2083" && t.cache.received_quantity !== "0",
    );
    expect(destinationTask).toBeDefined();
    // After transfer_send: материал принят и сразу выдан в работу (received == issued).
    expect(destinationTask!.status).toBe("in_progress");
    expect(Number(destinationTask!.cache.received_quantity)).toBe(10);
    expect(Number(destinationTask!.cache.issued_quantity)).toBe(10);

    // Тест завершён: после transfer_send задача in_progress, 10 в работе.
  });
});
