import { test, expect } from "./fixtures";
import { createProductViaUI, deleteProductViaUI } from "./ui-helpers";

/**
 * @smoke — создание артикула в справочнике сырья через UI, на КАЖДЫЙ прогон.
 *
 * Зачем отдельная проверка: `ensureProductViaUI` выходит рано, если SKU уже
 * есть в справочнике, поэтому на накопительной БД стенда путь создания не
 * исполнялся ВООБЩЕ, и в нём тихо копились поломки — заголовок диалога
 * «Новое сырье» (его в приложении нет, Ref #64) и текст «6000 мм» (ячейки
 * длин — <input>, в DOM текста нет). Обе чинились без прогона: тест, который
 * однажды прошёл, дальше зелёный всегда.
 *
 * Здесь артикул УНИКАЛЕН на каждый прогон, поэтому диалог открывается всегда
 * и проверка не зависит от чистоты БД. Артикул удаляется через UI в конце —
 * спека не копит мусор в справочнике.
 */
test.describe("@smoke Создание артикула в справочнике сырья через UI", () => {
  const TEST_SKU = `E2E-CREATE-${Date.now()}`;
  const TEST_NAME = `E2E проверка создания ${TEST_SKU}`;
  const TEST_LENGTH_MM = 6100;

  // Страховка уборки: упавший посреди теста прогон иначе оставил бы свой
  // артикул в справочнике навсегда. Молча — падение уже зафиксировано, но
  // причину печатаем: молчащий прогон, копящий мусор, не чинится.
  test.afterEach(async ({ authenticatedPage }) => {
    try {
      await authenticatedPage.goto("/references/raw-materials");
      const search = authenticatedPage.getByPlaceholder("Поиск");
      await expect(search).toBeVisible({ timeout: 10_000 });
      await search.fill(TEST_SKU);
      const row = authenticatedPage.locator("tr", { hasText: TEST_SKU }).first();
      // «Артикул есть» или «список пуст» — оба означают, что фильтр отработал.
      await expect(
        row.or(authenticatedPage.getByText("Ничего не найдено")).first(),
      ).toBeVisible({ timeout: 15_000 });
      if ((await row.count()) > 0) {
        await deleteProductViaUI(authenticatedPage, TEST_SKU);
      }
    } catch (e) {
      console.log(`[e2e:catalog-create] уборка ${TEST_SKU} не сработала:`, e);
    }
  });

  test("создать артикул с длиной, увидеть его в справочнике и удалить через UI", async ({
    authenticatedPage,
  }) => {
    test.slow();

    // 1. Создание через UI — диалог открывается всегда, раннего выхода нет.
    await createProductViaUI(authenticatedPage, TEST_SKU, TEST_NAME, TEST_LENGTH_MM);

    // 2. Артикул и его длина видны в списке.
    const search = authenticatedPage.getByPlaceholder("Поиск");
    await search.fill(TEST_SKU);
    const row = authenticatedPage.getByRole("row").filter({ hasText: TEST_SKU });
    await expect(row).toBeVisible({ timeout: 10_000 });
    await expect(row).toHaveCount(1);
    const lengthsCell = row.locator("td").nth(3);
    await expect(lengthsCell).toContainText(String(TEST_LENGTH_MM));
    await expect(lengthsCell).toContainText("мм");

    // 3. Название сохранилось — видно в карточке артикула.
    await row.locator("td").first().click();
    const card = authenticatedPage.getByRole("dialog");
    await expect(card).toBeVisible({ timeout: 5_000 });
    await expect(card.getByPlaceholder("ЮП-1234")).toHaveValue(TEST_SKU);
    await expect(card.getByPlaceholder("Полное название")).toHaveValue(TEST_NAME);
    await card.locator("form").getByRole("button", { name: "Закрыть" }).click();
    await expect(card).toBeHidden({ timeout: 5_000 });

    // 4. Удаление через UI: артикул уходит из справочника, спека самоочищается.
    await deleteProductViaUI(authenticatedPage, TEST_SKU);
    await expect(row).toBeHidden({ timeout: 10_000 });
  });
});
