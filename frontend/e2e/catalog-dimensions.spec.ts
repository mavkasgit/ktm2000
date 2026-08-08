import { test, expect } from "./fixtures";

/**
 * @smoke — E2E тест сохранения размеров 2D/3D в каталоге сырья.
 *
 * Реальный флоу: значения 2D/3D сохраняются через product_dimensions API
 * при сохранении карточки (edit). При создании сохраняется только
 * dimension_state, значения проставляются в карточке редактирования.
 */
test.describe("@smoke Catalog dimensions save & verify", () => {
  const TEST_SKU = `E2E-DIM-${Date.now()}`;

  test("create 2D product, fill dimensions, save and verify in list", async ({ authenticatedPage }) => {
    test.slow();

    // 1. Открываем каталог сырья
    await authenticatedPage.goto("/references/raw-materials");
    await expect(authenticatedPage.getByRole("heading", { name: "Справочник сырья" })).toBeVisible({ timeout: 15_000 });

    // 2. Создаём новый продукт
    await authenticatedPage.getByRole("button", { name: "Добавить" }).click();
    const dialog = authenticatedPage.getByRole("dialog");
    await expect(dialog).toBeVisible({ timeout: 5_000 });

    await dialog.getByPlaceholder("ЮП-1234").fill(TEST_SKU);
    await dialog.getByPlaceholder("Полное название").fill(`E2E Тестовый профиль ${TEST_SKU}`);

    // 3. Переключаем на 2D (area)
    await dialog.getByRole("button", { name: "2D" }).click();
    const lengthInput = dialog.locator(`label:has-text("Длина, мм")`).locator("..").locator("input");
    await expect(lengthInput).toBeVisible({ timeout: 3_000 });

    // 4. Сохраняем — на create уходит только dimension_state
    await dialog.getByRole("button", { name: "Создать" }).click();
    await expect(dialog).toBeHidden({ timeout: 10_000 });
    await expect(authenticatedPage.getByText(/создано/i).first()).toBeVisible({ timeout: 5_000 });

    // 5. Ищем продукт в списке
    const searchInput = authenticatedPage.getByPlaceholder("Поиск");
    await searchInput.fill(TEST_SKU);
    const row = authenticatedPage.getByRole("row").filter({ hasText: TEST_SKU });
    await expect(row).toBeVisible({ timeout: 5_000 });

    // 6. Открываем карточку и проставляем размеры 2D (реальный путь сохранения)
    await row.click();
    await expect(dialog).toBeVisible({ timeout: 5_000 });

    const widthInput = dialog.locator(`label:has-text("Ширина, мм")`).locator("..").locator("input");
    const thicknessInput = dialog.locator(`label:has-text("Толщина, мм")`).locator("..").locator("input");

    await lengthInput.fill("1200");
    await widthInput.fill("800");
    await thicknessInput.fill("2");

    await dialog.getByRole("button", { name: "Сохранить" }).click();
    await expect(dialog).toBeHidden({ timeout: 10_000 });

    // 7. Проверяем что в таблице отображаются размеры "1200×800×2 мм"
    await expect(row.getByText("1200×800×2 мм")).toBeVisible({ timeout: 5_000 });

    // 8. Открываем ещё раз — поля должны содержать сохранённые значения
    await row.click();
    await expect(dialog).toBeVisible({ timeout: 5_000 });

    const editLength = dialog.locator(`label:has-text("Длина, мм")`).locator("..").locator("input");
    const editWidth = dialog.locator(`label:has-text("Ширина, мм")`).locator("..").locator("input");
    const editThickness = dialog.locator(`label:has-text("Толщина, мм")`).locator("..").locator("input");

    await expect(editLength).toHaveValue("1200");
    await expect(editWidth).toHaveValue("800");
    await expect(editThickness).toHaveValue("2");

    // 9. Меняем толщину на 3 и сохраняем
    await editThickness.fill("3");
    await dialog.getByRole("button", { name: "Сохранить" }).click();
    await expect(dialog).toBeHidden({ timeout: 10_000 });

    // 10. Проверяем обновлённые размеры в таблице
    await expect(row.getByText("1200×800×3 мм")).toBeVisible({ timeout: 5_000 });
  });
});
