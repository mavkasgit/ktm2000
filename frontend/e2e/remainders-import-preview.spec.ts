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
 * Проверяет категории строк как в импорте плана: пропущенные скрыты по
 * умолчанию, открываются чипом «Пропущенные», «Ошибки» изолирует ошибочные,
 * повторный клик и «Сбросить» возвращают дефолт. Переключение чипа — клиентская
 * фильтрация: запроса нет. Смена сортировки идёт по `source_token`, без файла.
 *
 * Строка адресуется кодом 1С, а не точным текстом причины: подпись приходит с
 * сервера и может уточняться.
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

  test("категории строк: пропущенные скрыты, чипы, сортировка по токену", async ({ page }) => {
    // Считаем запросы предпросмотра: чипы не должны ходить на сервер (#472).
    let previewRequests = 0;
    page.on("request", (request) => {
      if (request.url().includes("/stock/import/remainders/preview")) previewRequests += 1;
    });

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

    // Счётчики считают весь лист, даже когда категория скрыта из таблицы.
    await expect(dialog.getByText("OK: 1 (40)", { exact: true })).toBeVisible();
    await expect(dialog.getByText("Пропущено: 1", { exact: true })).toBeVisible();
    await expect(dialog.getByText("Ошибок: 1", { exact: true })).toBeVisible();

    // Дефолт — годные и ошибочные: пропущенная строка (11820) скрыта.
    const rows = dialog.locator("tbody tr");
    await expect(rows).toHaveCount(2);
    await expect(dialog.getByRole("row").filter({ hasText: "11820" })).toHaveCount(0);
    await expect(dialog.getByRole("row").filter({ hasText: "99999" })).toHaveCount(1);

    const skippedChip = dialog.getByRole("button", { name: /^Пропущенные/ });
    const errorsChip = dialog.getByRole("button", { name: /^Ошибки/ });
    await expect(skippedChip).toHaveAttribute("aria-pressed", "false");
    await expect(errorsChip).toHaveAttribute("aria-pressed", "false");

    const requestsAfterPreview = previewRequests;

    // «Пропущенные» показывает только skipped — без сетевого запроса.
    await skippedChip.click();
    await expect(rows).toHaveCount(1);
    await expect(skippedChip).toHaveAttribute("aria-pressed", "true");
    await expect(errorsChip).toHaveAttribute("aria-pressed", "false");
    const skippedRow = dialog.getByRole("row").filter({ hasText: "11820" });
    await expect(skippedRow).toHaveCount(1);
    await expect(skippedRow).toContainText("Шкала РТБ-1560.00.00.001");
    const skippedErrors = skippedRow.getByRole("cell").filter({ hasText: /Пропущено: / });
    await expect(skippedErrors).toHaveCount(1);
    await expect(skippedErrors).toContainText(/^Пропущено: /);
    expect(previewRequests).toBe(requestsAfterPreview);

    // Повторный клик по активному чипу — снова дефолт.
    await skippedChip.click();
    await expect(rows).toHaveCount(2);
    await expect(skippedChip).toHaveAttribute("aria-pressed", "false");

    // «Ошибки» взаимоисключающий: остаётся только ошибочная строка.
    await errorsChip.click();
    await expect(rows).toHaveCount(1);
    await expect(dialog.getByRole("row").filter({ hasText: "99999" })).toHaveCount(1);
    await expect(dialog.getByRole("row").filter({ hasText: "11820" })).toHaveCount(0);
    await expect(errorsChip).toHaveAttribute("aria-pressed", "true");
    expect(previewRequests).toBe(requestsAfterPreview);

    // «Сбросить» возвращает дефолт и снимает чип.
    await dialog.getByRole("button", { name: "Сбросить" }).click();
    await expect(rows).toHaveCount(2);
    await expect(errorsChip).toHaveAttribute("aria-pressed", "false");
    expect(previewRequests).toBe(requestsAfterPreview);

    // Сортировка — новый запрос, но файл не отправляется: лист уже на сервере
    // под `source_token` (#472).
    const tokenRequest = page.waitForRequest(
      (request) =>
        request.url().includes("/stock/import/remainders/preview") &&
        (request.postData() ?? "").includes("source_token"),
    );
    const sortButton = dialog
      .getByRole("columnheader", { name: /Артикул/ })
      .getByRole("button");
    await sortButton.click();
    const tokenPayload = (await tokenRequest).postDataBuffer()?.toString("utf8") ?? "";
    expect(tokenPayload).toContain("source_token");
    expect(tokenPayload).not.toContain('filename="');

    // Футера пагинации нет: диалог показывает лист целиком.
    await expect(dialog.getByText(/Страница \d+ из \d+/)).toHaveCount(0);
  });
});
