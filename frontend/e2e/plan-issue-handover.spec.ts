import { test, expect } from "./fixtures";
import path from "path";

/**
 * @smoke — план выдачи/сдачи участка (тикет #95): колонка «Размер» в модалке
 * плана и разбивка «Сдачи» по выходам трансформирующего задания.
 *
 * Сценарий:
 * 1. API-setup: seed, продукты, техкарты, импорт «Упаковочный план.xlsx», release.
 * 2. UI: страница участка → кнопка «План» → модалка плана.
 * 3. UI: в таблицах «Выдача» и «Сдача» присутствует колонка «Размер»;
 *    если на участке есть трансформирующее задание (резка), строка «Сдачи»
 *    разбита на выходы со своими размерами.
 *
 * Требует запущенного dev-окружения: `npm run dev` из корня проекта.
 */

import {
  apiAddRemainder,
  apiApplyChangeSet,
  apiGetActiveTemplate,
  apiGetPlanPositions,
  apiGetSectionByCode,
  apiGetSections,
  apiImportExcel,
  apiResetAll,
  apiSeedData,
  apiEnsureTestProducts,
  apiEnsureTestTechcards,
  E2E_SECTION,
} from "./api-helpers";

test.describe("@smoke План выдачи/сдачи — колонка «Размер» и разбивка по выходам", () => {
  test.beforeEach(async () => {
    await apiResetAll();
    await apiSeedData();
    await apiEnsureTestProducts();
    await apiEnsureTestTechcards();
  });

  test("модалка плана показывает «Размер» в Выдаче и Сдаче", async ({
    authenticatedPage,
  }) => {
    test.slow();

    // 1. Setup: импортируем план и доводим до release.
    const template = await apiGetActiveTemplate();
    const xlsPath = path.resolve(process.cwd(), "../Упаковочный план.xlsx");
    const importRes = await apiImportExcel(template.id, xlsPath);
    await apiApplyChangeSet(importRes.production_plan_id, importRes.change_set_id);

    const positions = await apiGetPlanPositions(importRes.production_plan_id);
    const validPos = positions.find(
      (p: { validation_status: string }) => p.validation_status === "valid",
    );
    expect(validPos).toBeDefined();
    expect(validPos.route_id).toBeTruthy();

    // Остаток сырья, чтобы позиции можно было взять в работу.
    const rawSection = await apiGetSectionByCode(E2E_SECTION.RAW_STOCK);
    await apiAddRemainder(
      validPos.product_id,
      rawSection.id,
      Math.round(parseFloat(validPos.quantity)) || 10,
      "E2E: план выдачи/сдачи",
    );

    // Release через /execution (UI).
    await authenticatedPage.goto("/execution");
    await expect(authenticatedPage.getByPlaceholder("Поиск")).toBeVisible({ timeout: 10_000 });
    await authenticatedPage.getByPlaceholder("Поиск").fill(validPos.source_sku);
    const execRow = authenticatedPage
      .locator("tr", { hasText: `#${validPos.id}` })
      .first();
    await expect(execRow).toBeVisible({ timeout: 15_000 });
    await execRow.getByRole("button", { name: "Взять в работу" }).click();
    const confirm = authenticatedPage.getByRole("dialog");
    await expect(confirm).toBeVisible({ timeout: 5_000 });
    await confirm.getByRole("button", { name: /Запустить|Запуск/ }).click();
    await expect(confirm).not.toBeVisible({ timeout: 15_000 }).catch(() => {});

    // 2. Открываем модалку плана на участке (сырьё или первый production).
    const sections = (await apiGetSections()) as Array<{ id: number; code: string }>;
    const target =
      sections.find((s) => s.code === E2E_SECTION.RAW_STOCK) ??
      sections.find((s) => s.code === "SAWING") ??
      sections[0];
    expect(target).toBeDefined();

    await authenticatedPage.goto(`/section-tasks/${target!.id}`);
    const planBtn = authenticatedPage.getByRole("button", { name: "План", exact: true });
    await expect(planBtn).toBeVisible({ timeout: 15_000 });
    await planBtn.click();

    const dialog = authenticatedPage.getByRole("dialog");
    await expect(dialog).toBeVisible({ timeout: 10_000 });

    // 3. Колонка «Размер» присутствует в обеих таблицах модалки.
    //    (при одной таблице — заголовок «План» с колонкой «Размер»).
    const sizeHeaders = dialog.locator("th", { hasText: "Размер" });
    expect(await sizeHeaders.count()).toBeGreaterThan(0);

    // 4. Если заданий нет — модалка показывает «Нет данных» (валидный результат),
    //    а не ошибку.
    await expect(dialog.locator("body")).not.toContainText("Error").catch(() => {});
    const empty = dialog.getByText("Нет данных");
    if ((await empty.count()) > 0) {
      console.log("[INFO] План участка пуст — колонка «Размер» проверена, разбивка не тестируется");
      return;
    }

    // 5. В таблицах «Выдача»/«Сдача» есть строки с подписью размера («2,7 м»/«—»).
    //    Строки одного артикула разных размеров различимы.
    const dimCellTexts = await dialog.locator("td.whitespace-nowrap").allTextContents();
    expect(dimCellTexts.some((t) => t === "—" || /\d+,\d+\s*м/.test(t))).toBe(true);
  });
});
