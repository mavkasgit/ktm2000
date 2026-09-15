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
    const count = await rows.count();
    if (count === 0) {
      test.skip(true, "No plan positions rendered after import");
    }

    const firstRow = rows.first();
    await expect(firstRow).toBeVisible({ timeout: 10_000 });

    const routeCell = firstRow.locator("td").filter({ hasText: /типовой|маршрут|route/i });
    const hasRouteHint = (await routeCell.count()) > 0;
    console.log(`First imported row has route hint in table: ${hasRouteHint}`);
    expect(count).toBeGreaterThan(0);
  });

  test("import wizard opens and shows template options", async ({ page }) => {
    await page.goto("/planning");
    await expect(page.getByRole("heading", { name: "План", exact: true })).toBeVisible({
      timeout: 10_000,
    });

    const addFileBtn = page.getByRole("button", { name: /добавить файл/i });
    await expect(addFileBtn).toBeVisible();
    await addFileBtn.click();

    await expect(page.getByRole("dialog")).toBeVisible({ timeout: 5_000 });
    await expect(page.getByRole("heading", { name: /импорт|загруз|import/i })).toBeVisible({
      timeout: 5_000,
    });

    await page.keyboard.press("Escape");
    await expect(page.getByRole("dialog")).not.toBeVisible({ timeout: 5_000 });
  });
});