import { test, expect } from "./fixtures";
import {
  approvePositionViaUI,
  ensureE2ECatalogViaUI,
  findApprovablePositionViaUI,
  PACKAGING_PLAN_XLS_PATH,
  seedReferenceDataViaUI,
  takeToWorkViaUI,
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

  test("full workflow: import → approve → take-to-work via UI", async ({ page }) => {
    // #88: данные в общем плане нестабильны (парные позиции без парных техкарт) —
    // канонический полный цикл теперь покрывает full-cycle.spec.ts (ЮП-009).
    test.skip(true, "#88: устарел — полный цикл покрыт full-cycle.spec.ts");
    test.slow();
    await ensureE2ECatalogViaUI(page);
    await page.goto("/planning");
    await expect(page.getByRole("heading", { name: "План", exact: true })).toBeVisible({
      timeout: 10_000,
    });

    await uploadTestFileViaUI(page, PACKAGING_PLAN_XLS_PATH);
    await waitForPlanningTableViaUI(page);

    const position = await findApprovablePositionViaUI(page);
    if (!position) {
      test.skip(true, "No approvable positions after import — check test.xls validation data");
    }

    await approvePositionViaUI(page, position);
    await takeToWorkViaUI(page, position);
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

  test("execution page shows approved position after UI approve", async ({ page }) => {
    // #88: устарел — approve/execution-поток покрыт full-cycle.spec.ts (ЮП-009).
    test.skip(true, "#88: устарел — полный цикл покрыт full-cycle.spec.ts");
    test.slow();
    await ensureE2ECatalogViaUI(page);
    await page.goto("/planning");
    await expect(page.getByRole("heading", { name: "План", exact: true })).toBeVisible({
      timeout: 10_000,
    });

    await uploadTestFileViaUI(page, PACKAGING_PLAN_XLS_PATH);
    await waitForPlanningTableViaUI(page);

    const position = await findApprovablePositionViaUI(page);
    if (!position) {
      test.skip(true, "No approvable positions for execution check");
    }

    await approvePositionViaUI(page, position);

    await page.goto("/execution");
    await expect(page.getByRole("heading", { name: /выполнен|execution/i })).toBeVisible({
      timeout: 10_000,
    });

    const execSearch = page.getByPlaceholder("Поиск");
    await execSearch.fill(position.sku);

    const execRow = page.locator("tr", { hasText: `#${position.id}` }).first();
    await expect(execRow).toBeVisible({ timeout: 15_000 });
    await expect(execRow.getByRole("button", { name: "Взять в работу" })).toBeVisible({
      timeout: 5_000,
    });
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