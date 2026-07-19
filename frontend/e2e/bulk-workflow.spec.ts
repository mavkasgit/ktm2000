import { test, expect } from "./fixtures";
import path from "path";
import {
  apiApplyChangeSet,
  apiBatchAssignRoute,
  apiGetActiveRoutes,
  apiGetActiveTemplate,
  apiGetOrCreateTechcard,
  apiGetPlanPositions,
  apiGetProductBySku,
  apiGetSections,
  apiGetSpgs,
  apiImportExcel,
  apiEnsureTestProducts,
  apiEnsureTestTechcards,
  apiSeedData,
  E2E_SECTION,
} from "./api-helpers";

// --- Test Suite ---

/** @smoke — API-assisted setup; не канон E2E. См. @ui в route-workflow.spec.ts */
test.describe("@smoke Bulk operations workflow E2E", () => {
  test.beforeEach(async () => {
    // 1. Вызвать API-эндпоинт /api/routes-seed?force=true для сброса и наполнения справочников
    await apiSeedData();
    await apiEnsureTestProducts();
    await apiEnsureTestTechcards();
  });

  test("should complete workflow using bulk operations on the shopfloor", async ({ authenticatedPage }) => {
    test.slow();

    // Логируем все ответы с ошибками от API бэкенда для отладки
    authenticatedPage.on("response", async (response) => {
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

    // 2. Получить существующие продукты ЮП-3270 и ЮП-2083 и начислить стартовые остатки сырья на склад STOCK
    const productYu = await apiGetProductBySku("ЮП-3270");
    const product2083 = await apiGetProductBySku("ЮП-2083");
    console.log(`Found products: ЮП-3270 = ${productYu.id}, ЮП-2083 = ${product2083.id}`);

    // Убеждаемся, что у них есть техкарта
    await apiGetOrCreateTechcard(productYu.id);
    await apiGetOrCreateTechcard(product2083.id);

    const spgs = await apiGetSpgs();
    const sections = await apiGetSections();

    const spgStock = spgs.find((s: any) => s.code === "STOCK");
    const sectionWh = sections.find((s: any) => s.code === E2E_SECTION.RAW_STOCK);
    expect(spgStock).toBeDefined();
    expect(sectionWh).toBeDefined();

    // Начисляем 20 000 шт. для ЮП-3270 и ЮП-2083 на склад STOCK визуально через UI
    await authenticatedPage.goto("/spg");
    await expect(authenticatedPage.getByRole("heading", { name: "Группы хранения и производства" })).toBeVisible({ timeout: 15_000 });

    // Выбираем группу "Склад" в селекторе ГХП
    const spgSkladBtn = authenticatedPage.getByRole("button", { name: /^Склад/ }).first();
    await expect(spgSkladBtn).toBeVisible({ timeout: 5_000 });
    await spgSkladBtn.click();
    await expect(authenticatedPage.getByRole("button", { name: "Ручная операция" })).toBeVisible({
      timeout: 5_000,
    });

    const targetSkus = ["ЮП-3270", "ЮП-2083"];
    for (const sku of targetSkus) {
      console.log(`Entering starting stock for ${sku} via UI...`);
      // Нажимаем кнопку «Ручная операция»
      const manualOpBtn = authenticatedPage.getByRole("button", { name: "Ручная операция" }).first();
      await expect(manualOpBtn).toBeVisible({ timeout: 5_000 });
      await manualOpBtn.click();

      // Дожидаемся открытия диалога
      const dialog = authenticatedPage.getByRole("dialog");
      await expect(dialog).toBeVisible({ timeout: 5_000 });

      // Вводим артикул в поле поиска продукта
      const searchInput = dialog.getByPlaceholder("Поиск по артикулу или названию...");
      await searchInput.fill(sku);

      // Кликаем по найденной опции с нужным артикулом
      const productOption = dialog.locator("button", { hasText: sku }).first();
      await expect(productOption).toBeVisible({ timeout: 5_000 });
      await productOption.click();

      // Выбираем тип «Приход» (он выбран по умолчанию, но кликнем для надежности)
      const inBtn = dialog.getByRole("button", { name: "Приход" });
      await expect(inBtn).toBeVisible({ timeout: 5_000 });
      await inBtn.click();

      // Выбираем участок WH
      const sectionSelect = dialog.locator("select");
      await sectionSelect.selectOption(sectionWh.id.toString());

      // Заполняем количество 20 000
      const qtyInput = dialog.getByPlaceholder("0");
      await qtyInput.fill("20000");

      // Вводим основание
      const reasonInput = dialog.getByPlaceholder("например, возврат от заказчика / списание брака / корректировка остатков");
      await reasonInput.fill("Начальный избыток сырья E2E");

      // Кликаем «Сохранить»
      const saveBtn = dialog.getByRole("button", { name: "Сохранить" });
      await expect(saveBtn).toBeVisible({ timeout: 5_000 });
      await saveBtn.click();

      // Убеждаемся, что диалог закрылся
      await expect(dialog).not.toBeVisible({ timeout: 10_000 });
    }

    // Проверяем, что остатки отображаются в таблице на странице
    await expect(authenticatedPage.locator("tr", { hasText: "ЮП-3270" }).first()).toContainText("20000");
    await expect(authenticatedPage.locator("tr", { hasText: "ЮП-2083" }).first()).toContainText("20000");
    console.log("Initial raw stock remainders successfully added and verified via UI!");

    // 3. Импортировать файл test.xls через API, применить изменения плана
    const template = await apiGetActiveTemplate();
    let xlsPath = path.resolve(process.cwd(), "../test.xls");
    if (!fs.existsSync(xlsPath)) {
      xlsPath = path.resolve(process.cwd(), "test.xls");
    }
    console.log("Importing plan workbook from:", xlsPath);
    const importRes = await apiImportExcel(template.id, xlsPath);
    console.log("Imported plan, Production Plan ID:", importRes.production_plan_id);

    const applyRes = await apiApplyChangeSet(importRes.production_plan_id, importRes.change_set_id);
    console.log("Apply changes result:", applyRes);

    // 4. Получить список созданных позиций плана, отфильтровать позиции для ЮП-3270 и ЮП-2083
    const positions = await apiGetPlanPositions(importRes.production_plan_id);
    const filteredPositions = positions.filter(
      (p: any) => p.source_sku === "ЮП-3270" || p.source_sku === "ЮП-2083"
    );
    
    // Выбираем не менее 7-8 позиций
    const selectedPositions = filteredPositions.slice(0, 8);
    console.log(`Filtered ${selectedPositions.length} positions for bulk workflow`);
    expect(selectedPositions.length).toBeGreaterThanOrEqual(7);

    // Назначить им маршруты, если они не назначены
    const activeRoutes = await apiGetActiveRoutes();
    expect(activeRoutes.length).toBeGreaterThan(0);
    const routeId = activeRoutes[0].id;

    const unassignedPositionIds = selectedPositions
      .filter((p: any) => p.route_id === null)
      .map((p: any) => p.id);

    if (unassignedPositionIds.length > 0) {
      console.log(`Assigning route to ${unassignedPositionIds.length} positions`);
      await apiBatchAssignRoute(importRes.production_plan_id, unassignedPositionIds, routeId);
    }

    // 5. Перейти на страницу /planning и утвердить все эти 7-8 позиций в групповом (bulk) режиме
    await authenticatedPage.goto("/planning");
    const planSearch = authenticatedPage.getByPlaceholder("Поиск");
    await expect(planSearch).toBeVisible({ timeout: 10_000 });

    // Кликаем по кнопке "Групповые операции" для перехода в режим группового выделения
    const bulkModeBtn = authenticatedPage.getByRole("button", { name: "Групповые операции" });
    await expect(bulkModeBtn).toBeVisible({ timeout: 5_000 });
    await bulkModeBtn.click();

    // Ожидаем появления заголовка группового режима, чтобы React успел обновиться
    await expect(authenticatedPage.locator('span.text-lg:has-text("Групповые операции")').first()).toBeVisible({ timeout: 5_000 });

    // Кликаем по строкам нужных позиций (по ячейке с ID, чтобы не задеть выпадающий список маршрута)
    for (const pos of selectedPositions) {
      console.log(`Selecting position #${pos.id} on /planning in bulk mode`);
      const row = authenticatedPage.locator(`#plan-position-${pos.id}`);
      await expect(row).toBeVisible({ timeout: 10_000 });
      await row.getByText(pos.source_sku).first().click();
    }

    const bulkApproveBtn = authenticatedPage.locator(".mb-3").getByRole("button", { name: /^Утвердить$/ });
    await expect(bulkApproveBtn).toBeVisible({ timeout: 5_000 });
    await bulkApproveBtn.click();

    // Сделаем скриншот для отладки состояния после клика по кнопке Утвердить
    await authenticatedPage.waitForTimeout(2000);
    await authenticatedPage.screenshot({ path: "test-results/after-approve-click.png" });

    // Ожидаем скрытия групповой кнопки (что означает окончание процесса утверждения)
    await expect(bulkApproveBtn).not.toBeVisible({ timeout: 15_000 });
    console.log("All selected positions approved in bulk mode");

    // 6. Перейти на страницу /execution и запустить в работу все эти 7-8 позиций в групповом (bulk) режиме
    await authenticatedPage.goto("/execution");
    const execSearch = authenticatedPage.getByPlaceholder("Поиск");
    await expect(execSearch).toBeVisible({ timeout: 10_000 });

    // Кликаем по кнопке "Групповые операции" на странице Диспетчеризации
    const bulkModeExecBtn = authenticatedPage.getByRole("button", { name: "Групповые операции" });
    await expect(bulkModeExecBtn).toBeVisible({ timeout: 5_000 });
    await bulkModeExecBtn.click();

    // Ожидаем появления заголовка группового режима
    await expect(authenticatedPage.locator('span.text-lg:has-text("Групповые операции")').first()).toBeVisible({ timeout: 5_000 });

    // Кликаем по строкам нужных позиций (по ячейке с ID)
    for (const pos of selectedPositions) {
      console.log(`Selecting position #${pos.id} on /execution in bulk mode`);
      const row = authenticatedPage.locator("tr", { hasText: `#${pos.id}` }).first();
      await expect(row).toBeVisible({ timeout: 10_000 });
      await row.getByText(pos.source_sku).first().click();
    }

    const bulkLaunchBtn = authenticatedPage.locator('div.flex-wrap').getByRole('button', { name: /^Взять в работу/ });
    await expect(bulkLaunchBtn).toBeVisible({ timeout: 5_000 });
    await bulkLaunchBtn.click();

    // Ожидаем завершения запуска (кнопка пропадает)
    await expect(bulkLaunchBtn).not.toBeVisible({ timeout: 20_000 });
    console.log("All selected positions launched in bulk mode");

    // 7. Перейти на страницу /shopfloor-tasks/ID?bulk=1 (первый участок). Убедиться, что включен bulk-режим
    await authenticatedPage.goto(`/shopfloor-tasks/${sectionWh.id}?bulk=1`);
    await expect(authenticatedPage).toHaveURL(/bulk=1/);

    const bulkModeToggle = authenticatedPage.getByRole("button", { name: "Групповые операции" });
    await expect(bulkModeToggle).toBeVisible({ timeout: 10_000 });
    // Проверим, что кнопка групповых операций активна (имеет класс, отличный от outline, например default/bg-primary)
    await expect(bulkModeToggle).toHaveClass(/bg-primary|default/);

    // 8. Отметить чекбоксы для всех 7-8 запущенных задач в таблице (найти строки задач по ID или артикулу)
    // Ждем загрузки задач в таблице
    await expect(authenticatedPage.locator('tr:has-text("ЮП-3270")').first()).toBeVisible({ timeout: 15_000 });
    await expect(authenticatedPage.locator('tr:has-text("ЮП-2083")').first()).toBeVisible({ timeout: 15_000 });

    // Развернем все группы задач, чтобы видеть индивидуальные строки
    let expandBtn = authenticatedPage.locator('button[title="Раскрыть"]').first();
    while (await expandBtn.isVisible()) {
      await expandBtn.click();
      await authenticatedPage.waitForTimeout(200); // Дадим время для анимации раскрытия и перерендеринга
      expandBtn = authenticatedPage.locator('button[title="Раскрыть"]').first();
    }

    // Выбираем индивидуальные строки задач, кликая по ним
    const taskRowsYu = authenticatedPage.locator('tr:has-text("ЮП-3270")').filter({ has: authenticatedPage.getByRole('button', { name: /^Завершить$/ }) });
    const taskRows2083 = authenticatedPage.locator('tr:has-text("ЮП-2083")').filter({ has: authenticatedPage.getByRole('button', { name: /^Завершить$/ }) });

    const yuCount = await taskRowsYu.count();
    console.log(`Clicking ${yuCount} task rows for ЮП-3270`);
    for (let i = 0; i < yuCount; i++) {
      await taskRowsYu.nth(i).click();
    }

    const count2083 = await taskRows2083.count();
    console.log(`Clicking ${count2083} task rows for ЮП-2083`);
    for (let i = 0; i < count2083; i++) {
      await taskRows2083.nth(i).click();
    }

    // 9. Убедиться, что сверху появилась панель BulkOperationsPanel.
    const bulkPanel = authenticatedPage.locator('div.rounded-lg.border.bg-card.inline-block');
    await expect(bulkPanel).toBeVisible({ timeout: 10_000 });

    // Нажать в ней кнопку "План", чтобы скопировать плановые количества в инпуты годной продукции
    const planBtn = bulkPanel.getByRole('button', { name: 'План' }).first();
    await planBtn.click();
    console.log("Clicked 'План' button to copy planned quantities in BulkOperationsPanel");

    // 10. Для нескольких задач ввести небольшое количество брака (например, 2-3 шт.) в соответствующие поля ввода
    const bulkRowYu = bulkPanel.locator('tr', { hasText: 'ЮП-3270' }).first();
    const defectInputYu = bulkRowYu.locator('input[type="number"]').nth(1); // второй input в строке - это брак (defectQty)
    await defectInputYu.fill('2');

    const bulkRow2083 = bulkPanel.locator('tr', { hasText: 'ЮП-2083' }).first();
    const defectInput2083 = bulkRow2083.locator('input[type="number"]').nth(1);
    await defectInput2083.fill('3');
    console.log("Defect quantities entered for Yu-3270 and Yu-2083 groups");

    // 11. Нажать кнопку "Подтвердить" в BulkOperationsPanel. Дождаться тоста об успешном выполнении
    const confirmBtn = bulkPanel.getByRole('button', { name: 'Подтвердить' });
    await expect(confirmBtn).toBeEnabled();
    await confirmBtn.click();

    // Ожидание тоста об успешном завершении массовой операции
    const toastMessage = authenticatedPage.locator('text=Массовая операция выполнена').first();
    await expect(toastMessage).toBeVisible({ timeout: 20_000 });
    console.log("Bulk completion submitted and success toast received");

    // 12. Проверить, что выбранные задачи завершены, а на складе /spg (вкладка Склад) отображается выполненное количество продукции
    await authenticatedPage.goto("/spg");
    await expect(authenticatedPage.getByRole("heading", { name: "Группы хранения и производства" })).toBeVisible({ timeout: 10_000 });

    const stockTabBtn = authenticatedPage.getByRole("button", { name: /Склад/ }).first();
    await expect(stockTabBtn).toBeVisible({ timeout: 5_000 });
    await stockTabBtn.click();

    // Проверяем выполненное количество для ЮП-3270 (индекс 3 в строке таблицы - Выполнено)
    const rowStockYu = authenticatedPage.locator("tr", { hasText: "ЮП-3270" }).first();
    await expect(rowStockYu).toBeVisible({ timeout: 10_000 });
    const cellsYu = rowStockYu.locator("td");
    const qtyYu = await cellsYu.nth(3).textContent();
    console.log(`Completed quantity of ЮП-3270 on STOCK warehouse: ${qtyYu}`);
    expect(parseFloat(qtyYu || "0")).toBeGreaterThan(0);

    // Проверяем выполненное количество для ЮП-2083 (индекс 3 в строке таблицы - Выполнено)
    const rowStock2083 = authenticatedPage.locator("tr", { hasText: "ЮП-2083" }).first();
    await expect(rowStock2083).toBeVisible({ timeout: 10_000 });
    const cells2083 = rowStock2083.locator("td");
    const qty2083 = await cells2083.nth(3).textContent();
    console.log(`Completed quantity of ЮП-2083 on STOCK warehouse: ${qty2083}`);
    expect(parseFloat(qty2083 || "0")).toBeGreaterThan(0);

    // 13. Перейти на страницу /transfers и выполнить групповую передачу отправленных объемов
    await authenticatedPage.goto("/transfers");
    await expect(authenticatedPage.getByRole("heading", { name: "Передачи между ГХП" })).toBeVisible({ timeout: 10_000 });

    // Выберем ГХП "STOCK" (Склад)
    const spgTrigger = authenticatedPage.locator('button:has-text("Выберите ГХП"), button:has-text("STOCK")').first();
    await spgTrigger.click();
    const spgOption = authenticatedPage.locator('div[role="option"]', { hasText: "STOCK" }).first();
    await spgOption.click();
    console.log("SPG STOCK selected in transfers filter");

    // Включаем групповые операции
    const bulkTransfersBtn = authenticatedPage.getByRole("button", { name: "Групповые операции" });
    await expect(bulkTransfersBtn).toBeVisible({ timeout: 5_000 });
    await bulkTransfersBtn.click();

    // Ждем появления строк готовых к передаче
    await expect(authenticatedPage.locator('tr:has-text("ЮП-3270")').first()).toBeVisible({ timeout: 10_000 });
    await expect(authenticatedPage.locator('tr:has-text("ЮП-2083")').first()).toBeVisible({ timeout: 10_000 });

    // Выбираем все готовые задачи кликом по чекбоксу в шапке таблицы
    const selectAllCheckbox = authenticatedPage.locator('thead th button[role="checkbox"], thead th input[type="checkbox"]').first();
    await selectAllCheckbox.click();
    console.log("All ready tasks selected for transfer");

    // Нажимаем "Передать выбранные" в панели групповых операций
    const bulkTransferSubmitBtn = authenticatedPage.getByRole("button", { name: "Передать выбранные" });
    await expect(bulkTransferSubmitBtn).toBeVisible({ timeout: 5_000 });
    await bulkTransferSubmitBtn.click();

    // Заполняем комментарий в модальном окне и подтверждаем групповую отправку
    const bulkTransferDialog = authenticatedPage.locator('div[role="dialog"]');
    await expect(bulkTransferDialog).toBeVisible({ timeout: 5_000 });
    await bulkTransferDialog.getByPlaceholder("Опционально (применится ко всем передачам)").fill("Групповой E2E перенос");
    await bulkTransferDialog.getByRole("button", { name: "Отправить все" }).click();

    // Ожидаем успешный тост
    const transferToast = authenticatedPage.locator('text=Передача выполнена').first();
    await expect(transferToast).toBeVisible({ timeout: 20_000 });
    console.log("Bulk transfer successfully completed and verified in UI!");

    // 14. Снова перейти на страницу /spg и проверить, что начальные остатки сырья STOCK уменьшились (были полностью потреблены и исчезли из активных остатков)
    await authenticatedPage.goto("/spg");
    await expect(authenticatedPage.getByRole("heading", { name: "Группы хранения и производства" })).toBeVisible({ timeout: 10_000 });

    const stockTabFinalBtn = authenticatedPage.getByRole("button", { name: /Склад/ }).first();
    await expect(stockTabFinalBtn).toBeVisible({ timeout: 5_000 });
    await stockTabFinalBtn.click();

    const remaindersTabFinalBtn = authenticatedPage.getByRole("button", { name: "Остатки" }).first();
    await expect(remaindersTabFinalBtn).toBeVisible({ timeout: 5_000 });
    await remaindersTabFinalBtn.click();

    // Проверяем, что записи ЮП-3270 и ЮП-2083 больше не отображаются на вкладке Остатки
    const tableRowYu = authenticatedPage.locator("tr", { hasText: "ЮП-3270" }).first();
    await expect(tableRowYu).not.toBeVisible({ timeout: 10_000 });

    const tableRow2083 = authenticatedPage.locator("tr", { hasText: "ЮП-2083" }).first();
    await expect(tableRow2083).not.toBeVisible({ timeout: 10_000 });

    console.log("Bulk Operations Workflow E2E Test successfully completed and stock consumption verified!");
  });
});
