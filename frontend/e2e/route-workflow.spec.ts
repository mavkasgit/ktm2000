import { test, expect } from "./fixtures";
import {
  ensureE2ECatalogViaUI,
  PACKAGING_PLAN_XLS_PATH,
  seedReferenceDataViaUI,
  uploadTestFileViaUI,
  waitForPlanningTableViaUI,
} from "./ui-helpers";

/**
 * @ui — канонический E2E: только UI, без прямых fetch к бизнес-API.
 * Setup: Dev Settings → импорт → planning → execution.
 */

test.describe("@ui Route workflow E2E", () => {
  test.beforeEach(async ({ page, loginAsAdmin }) => {
    await loginAsAdmin();
    await seedReferenceDataViaUI(page);
  });

  test("position route info is visible in planning table after import", async ({ page }) => {
    test.slow();
    await ensureE2ECatalogViaUI(page);
    await page.goto("/planning");
    await expect(page.getByRole("heading", { name: "План", exact: true })).toBeVisible({
      timeout: 10_000,
    });

    await uploadTestFileViaUI(page, PACKAGING_PLAN_XLS_PATH);
    await waitForPlanningTableViaUI(page);

    const rows = page.locator('[id^="plan-position-"]');
    // Таблица плана грузится асинхронно: `count()` сразу после goto видел 0
    // строк на ещё не отрисованной таблице — и тест уходил в `test.skip`.
    // Ждём конкретное состояние (есть строка), а не «сколько бы ни нашлось».
    await expect(rows.first()).toBeVisible({ timeout: 30_000 });
    const count = await rows.count();

    const firstRow = rows.first();
    // Строка плана — CSS-grid из <div>, а не <table>: локатор `td` в ней не
    // находит ничего (маршрут читался как «нет подсказки» на любом прогоне).
    // Седьмая ячейка grid — «Маршрут» (порядок в PlanPositionRow).
    const routeCell = firstRow.locator("> div").nth(6);
    await expect(routeCell).toBeVisible({ timeout: 10_000 });
    // Живой импорт «Упаковочного плана» назначает маршрут каждой строке,
    // поэтому в ячейке имя маршрута, а не плейсхолдеры неразрешённого route.
    await expect(routeCell).not.toHaveText(/Не назначен|Нажмите для выбора/i);

    expect(count).toBeGreaterThan(0);
  });

  test("import wizard opens and shows template options", async ({ page }) => {
    await page.goto("/planning");
    await expect(page.getByRole("heading", { name: "План", exact: true })).toBeVisible({
      timeout: 10_000,
    });

    const addFileBtn = page.getByRole("button", { name: /добавить файл/i });
    await expect(addFileBtn).toBeVisible({ timeout: 10_000 });
    await addFileBtn.click();

    const wizard = page.getByRole("dialog");
    await expect(wizard).toBeVisible({ timeout: 10_000 });
    await expect(wizard.getByRole("heading", { name: /импорт|загруз|import/i })).toBeVisible({
      timeout: 10_000,
    });

    // Шаблон импорта выбирается на шаге загрузки, а список приезжает отдельным
    // запросом после открытия визарда — ждём его появления, а не факта диалога.
    const templateSelect = wizard.getByRole("combobox").first();
    await expect(templateSelect).toBeVisible({ timeout: 10_000 });
    await templateSelect.click();
    await expect(page.getByRole("option", { name: /Упаковочная карта РП/i })).toBeVisible({
      timeout: 10_000,
    });

    await page.keyboard.press("Escape");
    await page.keyboard.press("Escape");
    await expect(page.getByRole("dialog")).not.toBeVisible({ timeout: 10_000 });
  });
});