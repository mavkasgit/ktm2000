import path from "path";
import { fileURLToPath } from "url";

import { apiEnsureCatalogProduct } from "./api-helpers";
import { expect, test } from "./fixtures";
import { arriveAtRoute } from "./ui-helpers";

const __dirname = path.dirname(fileURLToPath(import.meta.url));

/**
 * Лист ОСВ 1С для предпросмотра импорта остатков: одна годная строка
 * (артикул ЮП-009 в наименовании), одна строка реестра исключений ОСВ
 * (код 11820 → «skipped», не ошибка) и одна неразобранная (каталог и реестр
 * её не знают → «invalid»). Шапка — как у реальной выгрузки 1С.
 */
const OSV_XLS_PATH = path.resolve(__dirname, "testdata/ОСВ E2E.xlsx");

/**
 * @ui — предпросмотр диалога «Импорт остатков» на листе 1С ОСВ.
 *
 * Проверяет то, ради чего диалог перестал листать страницы: лист приходит
 * целиком, поэтому оператор видит пропущенные строки вместе с причиной без
 * переключения страниц. Строка адресуется кодом 1С, а не точным текстом
 * причины: подпись приходит с сервера и может уточняться.
 *
 * Сетап данных — API: артикул ЮП-009, чтобы годная строка матчилась по
 * наименованию (привязка кода 1С не нужна). Реестр исключений ОСВ приходит
 * сидами стенда, поэтому код 11820 действительно пропускается.
 */
test.describe("@ui Предпросмотр импорта остатков из листа ОСВ", () => {
  test.beforeEach(async ({ loginAsAdmin }) => {
    await loginAsAdmin();
    await apiEnsureCatalogProduct({
      sku: "ЮП-009",
      name: "Профиль ЮП-009",
      lengthsMm: [2700],
    });
  });

  test("лист целиком: причина пропуска, счётчики и фильтр без пагинации", async ({ page }) => {
    await arriveAtRoute(page, "/spg");

    const importButton = page.getByRole("button", { name: "Импорт из Excel" });
    await expect(importButton).toBeVisible({ timeout: 15_000 });
    await importButton.click();

    const dialog = page.getByRole("dialog").filter({ hasText: "Импорт остатков" });
    await expect(dialog).toBeVisible({ timeout: 10_000 });
    await dialog.locator('input[type="file"]').setInputFiles(OSV_XLS_PATH);

    // Предпросмотр грузится после чтения листов; «Всего» считает строки листа,
    // а не страницу.
    await expect(dialog.getByText("Всего: 3", { exact: true })).toBeVisible({
      timeout: 30_000,
    });

    // Три строки листа на экране, без нарезки на страницы. Счётчики
    // подтверждают, что годная строка действительно годная (матч по ЮП-009).
    await expect(dialog.locator("tbody tr")).toHaveCount(3);
    await expect(dialog.getByText("OK: 1 (40)", { exact: true })).toBeVisible();
    await expect(dialog.getByText("Пропущено: 1", { exact: true })).toBeVisible();
    await expect(dialog.getByText("Ошибок: 1", { exact: true })).toBeVisible();
    await expect(dialog.getByText(/Показаны первые/)).toHaveCount(0);

    // Пропущенная строка — по коду 1С, в колонке «Ошибки» подпись начинается
    // с «Пропущено:», а причина остаётся читаемой (конкретная категория
    // приходит с сервера и в спеке не хардкодится).
    const skippedRow = dialog.getByRole("row").filter({ hasText: "11820" });
    await expect(skippedRow).toHaveCount(1);
    await expect(skippedRow).toContainText("Шкала РТБ-1560.00.00.001");
    const skippedErrors = skippedRow
      .getByRole("cell")
      .filter({ hasText: /Пропущено: / });
    await expect(skippedErrors).toHaveCount(1);
    await expect(skippedErrors).toContainText(/^Пропущено: /);

    // Фильтр статуса умеет показать только пропущенные строки.
    const statusFilter = dialog
      .getByRole("combobox")
      .filter({ hasText: "Все строки" });
    await expect(statusFilter).toHaveCount(1);
    await statusFilter.click();
    await expect(page.getByRole("option", { name: "Только пропущенные" })).toBeVisible();
    await page.keyboard.press("Escape");

    // Футера пагинации нет: диалог показывает лист целиком.
    await expect(dialog.getByText(/Страница \d+ из \d+/)).toHaveCount(0);
  });
});
