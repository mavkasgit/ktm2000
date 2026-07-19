import { expect, type Page } from "@playwright/test";
import path from "path";
import { fileURLToPath } from "url";

const __dirname = path.dirname(fileURLToPath(import.meta.url));

export const TEST_XLS_PATH = path.resolve(__dirname, "../../test.xls");
export const PACKAGING_PLAN_XLS_PATH = path.resolve(__dirname, "../../Упаковочный план.xlsx");

export const E2E_CATALOG_SKUS = [
  { sku: "ЮП-3270", name: "Профиль ЮП-3270", lengthMm: 6000 },
  { sku: "ЮП-2083", name: "Профиль ЮП-2083", lengthMm: 6000 },
] as const;

/** Подтвердить диалог «Запуск в производство» после «Взять в работу». */
export async function confirmProductionLaunchViaUI(page: Page) {
  const launchDialog = page.getByRole("dialog").filter({ hasText: "Запуск в производство" });
  await expect(launchDialog).toBeVisible({ timeout: 10_000 });
  const launchBtn = launchDialog.getByRole("button", { name: "Запустить в работу" });
  await expect(launchBtn).toBeEnabled({ timeout: 10_000 });
  await launchBtn.click();
  await expect(launchDialog).not.toBeVisible({ timeout: 15_000 });
}

/** Создать продукт в справочнике сырья через UI, если его ещё нет. */
export async function ensureProductViaUI(
  page: Page,
  sku: string,
  name: string,
  lengthMm = 6000,
) {
  await page.goto("/references/raw-materials");
  await expect(page.getByPlaceholder("Поиск")).toBeVisible({ timeout: 10_000 });

  const search = page.getByPlaceholder("Поиск");
  await search.fill(sku);
  await page.waitForTimeout(800);

  const existingRow = page.locator("tr", { hasText: sku }).first();
  if ((await existingRow.count()) > 0) {
    return;
  }

  await page.getByRole("button", { name: "Добавить" }).click();
  const dialog = page.getByRole("dialog");
  await expect(dialog).toBeVisible({ timeout: 5_000 });
  await expect(dialog.getByRole("heading", { name: "Новое сырье" })).toBeVisible();

  await dialog.locator('input[placeholder="ЮП-1234"]').fill(sku);
  await dialog.locator('input[placeholder="Полное название"]').fill(name);

  const lengthInput = dialog.getByPlaceholder("Введите длину");
  await lengthInput.fill(String(lengthMm));
  await dialog.getByRole("button", { name: "Добавить" }).click();
  await expect(dialog.getByText(`${lengthMm} мм`)).toBeVisible({ timeout: 5_000 });

  await dialog.getByRole("button", { name: "Создать" }).click();
  try {
    await expect(dialog).not.toBeVisible({ timeout: 15_000 });
  } catch {
    // SKU может уже существовать (например finished_good из smoke) — не виден в «Сырьё» (фильтр component).
    await dialog.getByRole("button", { name: "Закрыть" }).first().click();
    await expect(dialog).not.toBeVisible({ timeout: 5_000 });
  }
}

/** Массовое создание стандартных техкарт через UI (backend добавляет default line). */
export async function ensureStandardTechcardsViaUI(page: Page, skus: readonly string[]) {
  await page.goto("/references/techcards");
  await page.getByRole("button", { name: "Массовое создание" }).click();
  const dialog = page.getByRole("dialog");
  await expect(dialog).toBeVisible({ timeout: 10_000 });

  for (const sku of skus) {
    const row = dialog.locator("tr", { hasText: sku });
    if ((await row.count()) > 0) {
      await row.locator('input[type="checkbox"]').check();
    }
  }

  const applyBtn = dialog.getByRole("button", { name: "Применить" });
  if (await applyBtn.isEnabled()) {
    await applyBtn.click();
    await expect(dialog).not.toBeVisible({ timeout: 30_000 });
  } else {
    await dialog.getByRole("button", { name: "Отмена" }).click();
  }
}

export async function ensureE2ECatalogViaUI(page: Page) {
  for (const item of E2E_CATALOG_SKUS) {
    await ensureProductViaUI(page, item.sku, item.name, item.lengthMm);
  }
  await ensureStandardTechcardsViaUI(
    page,
    E2E_CATALOG_SKUS.map((item) => item.sku),
  );
}

/** Seed routes/templates via Dev Settings UI — no direct fetch. */
export async function seedReferenceDataViaUI(page: Page) {
  await page.goto("/settings/dev");
  await expect(page.getByRole("heading", { name: /панель разработчика/i })).toBeVisible({
    timeout: 10_000,
  });

  await page.getByRole("button", { name: "Загрузить справочники" }).click();
  await expect(page.getByRole("dialog")).toBeVisible({ timeout: 5_000 });

  await page.getByRole("dialog").getByRole("button", { name: /^Загрузить$/ }).click();

  const overwriteBtn = page.getByRole("button", { name: "Перезаписать" });
  await expect(overwriteBtn).toBeVisible({ timeout: 5_000 });
  await overwriteBtn.click();

  await expect(page.getByRole("alertdialog")).not.toBeVisible({ timeout: 60_000 });
  await expect(page.getByRole("dialog")).not.toBeVisible({ timeout: 60_000 });
}

/** Upload Excel plan via the planning import wizard. */
export async function uploadTestFileViaUI(page: Page, filePath = TEST_XLS_PATH) {
  const templateBtn = page.getByRole("button", { name: /Упаковочная карта РП/i });
  if ((await templateBtn.count()) > 0) {
    await templateBtn.click();
  } else {
    await page.getByRole("button", { name: "Добавить файл" }).click();
    const uploadWizard = page.getByRole("dialog");
    await expect(uploadWizard).toBeVisible({ timeout: 10_000 });
    const templateCombo = uploadWizard.getByRole("combobox").first();
    await templateCombo.click();
    await page.getByRole("option", { name: /Упаковочная карта РП/i }).click();
  }

  const wizard = page.getByRole("dialog");
  await expect(wizard).toBeVisible({ timeout: 10_000 });

  const fileInput = wizard.locator('input[type="file"]');
  await fileInput.setInputFiles(filePath);

  const applyBtn = wizard.getByRole("button", { name: /применить изменения/i });
  await expect(applyBtn).toBeEnabled({ timeout: 120_000 });

  await applyBtn.click();

  const confirmDialog = page.getByRole("alertdialog");
  await expect(confirmDialog).toBeVisible({ timeout: 10_000 });
  await confirmDialog
    .getByRole("button", { name: /загрузить с ошибками|загрузить \(/i })
    .first()
    .click();

  await expect(confirmDialog).not.toBeVisible({ timeout: 30_000 });
  await expect(wizard.getByText("Изменения применены")).toBeVisible({ timeout: 120_000 });
  await wizard.getByRole("button", { name: "Закрыть" }).first().click();
  await expect(wizard).not.toBeVisible({ timeout: 10_000 });
}

/** Дождаться активного плана и строк в таблице — без networkidle (polling ломает ожидание). */
export async function waitForPlanningTableViaUI(page: Page) {
  await expect(page.getByText("Нет активного плана")).not.toBeVisible({ timeout: 30_000 });
  await expect(page.getByRole("heading", { name: "Общий план" })).toBeVisible({ timeout: 15_000 });
  await expect(page.locator('[id^="plan-position-"]').first()).toBeVisible({ timeout: 30_000 });
}

export type ApprovablePosition = { id: number; sku: string };

/** Find a planning row that exposes the «Утвердить» action (UI-only). */
export async function findApprovablePositionViaUI(page: Page): Promise<ApprovablePosition | null> {
  const rows = page.locator('[id^="plan-position-"]').filter({
    has: page.getByRole("button", { name: "Утвердить" }),
  });
  const count = await rows.count();
  if (count === 0) {
    return null;
  }

  const row = rows.first();
  const rowId = await row.getAttribute("id");
  if (!rowId) {
    return null;
  }

  const positionId = Number.parseInt(rowId.replace("plan-position-", ""), 10);
  const skuCell = row.locator("td").first();
  const sku = ((await skuCell.textContent()) ?? "").trim();

  return Number.isFinite(positionId) ? { id: positionId, sku } : null;
}

export async function approvePositionViaUI(page: Page, position: ApprovablePosition) {
  const planSearch = page.getByPlaceholder("Поиск");
  await expect(planSearch).toBeVisible({ timeout: 10_000 });
  if (position.sku) {
    await planSearch.fill(position.sku);
  }

  const planRow = page.locator(`#plan-position-${position.id}`);
  await expect(planRow).toBeVisible({ timeout: 15_000 });

  const approveBtn = planRow.getByRole("button", { name: "Утвердить" });
  await expect(approveBtn).toBeVisible({ timeout: 5_000 });
  await approveBtn.click();

  const forceBtn = page.locator("button", { hasText: "Утвердить всё равно" }).filter({ visible: true });
  try {
    await expect(forceBtn).toBeVisible({ timeout: 3_000 });
    await forceBtn.click();
    await expect(page.getByRole("alertdialog")).not.toBeVisible({ timeout: 5_000 });
  } catch {
    // no risk dialog — ok
  }

  await expect(approveBtn).not.toBeVisible({ timeout: 15_000 });
}

export async function takeToWorkViaUI(page: Page, position: ApprovablePosition) {
  await page.goto("/execution");
  const execSearch = page.getByPlaceholder("Поиск");
  await expect(execSearch).toBeVisible({ timeout: 10_000 });

  if (position.sku) {
    await execSearch.fill(position.sku);
  }

  const execRow = page.locator("tr", { hasText: `#${position.id}` }).first();
  await expect(execRow).toBeVisible({ timeout: 15_000 });

  const launchBtn = execRow.getByRole("button", { name: "Взять в работу" });
  await expect(launchBtn).toBeVisible({ timeout: 5_000 });
  await launchBtn.click();
  await confirmProductionLaunchViaUI(page);

  await expect(execRow.locator("span").filter({ hasText: /^Запущен$/ })).toBeVisible({
    timeout: 15_000,
  });
}