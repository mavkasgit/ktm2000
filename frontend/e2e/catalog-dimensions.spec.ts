import { test, expect } from "./fixtures";
import { BACKEND_URL, apiGetProductBySku } from "./api-helpers";

/** @smoke — E2E тест сохранения размеров 2D/3D в каталоге. */
test.describe("@smoke Catalog dimensions save & verify", () => {
  const TEST_SKU = `E2E-DIM-${Date.now()}`;

  test("create 2D product, fill dimensions, save and verify in list", async ({ authenticatedPage }) => {
    test.slow();

    // 1. Открываем каталог
    await authenticatedPage.goto("/references/raw-materials");
    await expect(authenticatedPage.getByRole("heading", { name: /сырьё|каталог/i })).toBeVisible({ timeout: 15_000 });

    // 2. Нажимаем «Добавить» (кнопка с плюсом или «Новое сырьё»)
    const addBtn = authenticatedPage.getByRole("button", { name: /добавить|новое/i }).first();
    await expect(addBtn).toBeVisible({ timeout: 5_000 });
    await addBtn.click();

    // 3. Ждём открытия диалога
    const dialog = authenticatedPage.getByRole("dialog");
    await expect(dialog).toBeVisible({ timeout: 5_000 });

    // 4. Заполняем SKU и имя
    await dialog.getByLabel(/артикул|sku/i).first().fill(TEST_SKU);
    await dialog.getByLabel(/название|имя/i).first().fill(`E2E Тестовый профиль ${TEST_SKU}`);

    // 5. Переключаем на 2D (area) — нажимаем таб "2D"
    const tab2D = dialog.getByRole("button", { name: "2D" });
    await expect(tab2D).toBeVisible({ timeout: 3_000 });
    await tab2D.click();

    // 6. Заполняем поля размеров 2D
    // Поля по label: "Длина, мм", "Ширина, мм", "Толщина, мм"
    const lengthInput = dialog.getByLabel(/длина, мм/i);
    const widthInput = dialog.getByLabel(/ширина, мм/i);
    const thicknessInput = dialog.getByLabel(/толщина, мм/i);

    await expect(lengthInput).toBeVisible({ timeout: 3_000 });
    await lengthInput.fill("1200");
    await widthInput.fill("800");
    await thicknessInput.fill("2");

    // 7. Сохраняем — нажимаем кнопку «Сохранить» в диалоге
    const saveBtn = dialog.getByRole("button", { name: /сохранить|save/i }).first();
    await expect(saveBtn).toBeEnabled({ timeout: 5_000 });
    await saveBtn.click();

    // 8. Ждём закрытия диалога (сохранение прошло успешно)
    await expect(dialog).toBeHidden({ timeout: 10_000 });

    // 9. Проверяем что тост об успехе появился
    await expect(authenticatedPage.getByText(/создано|сохранено/i).first()).toBeVisible({ timeout: 5_000 });

    // 10. Ищем продукт в таблице и проверяем что размеры отображаются
    // Используем поиск чтобы найти наш продукт
    const searchInput = authenticatedPage.getByPlaceholder(/поиск/i).first();
    if (await searchInput.isVisible()) {
      await searchInput.fill(TEST_SKU);
      await authenticatedPage.waitForTimeout(500);
    }

    // Проверяем что в строке таблицы отображаются размеры "1200×800×2 мм"
    const row = authenticatedPage.getByRole("row").filter({ hasText: TEST_SKU });
    await expect(row).toBeVisible({ timeout: 5_000 });
    await expect(row.getByText("1200×800×2 мм")).toBeVisible({ timeout: 3_000 });

    // 11. Открываем продукт для редактирования — кликаем на строку
    await row.click();
    const editDialog = authenticatedPage.getByRole("dialog");
    await expect(editDialog).toBeVisible({ timeout: 5_000 });

    // 12. Проверяем что поля размеров заполнены сохранёнными значениями
    const editLength = editDialog.getByLabel(/длина, мм/i);
    const editWidth = editDialog.getByLabel(/ширина, мм/i);
    const editThickness = editDialog.getByLabel(/толщина, мм/i);

    await expect(editLength).toHaveValue("1200");
    await expect(editWidth).toHaveValue("800");
    await expect(editThickness).toHaveValue("2");

    // 13. Меняем толщину на 3
    await editThickness.fill("3");

    // 14. Сохраняем
    const editSaveBtn = editDialog.getByRole("button", { name: /сохранить|save/i }).first();
    await expect(editSaveBtn).toBeEnabled({ timeout: 5_000 });
    await editSaveBtn.click();

    // 15. Ждём закрытия диалога
    await expect(editDialog).toBeHidden({ timeout: 10_000 });

    // 16. Проверяем обновлённые размеры в таблице
    const updatedRow = authenticatedPage.getByRole("row").filter({ hasText: TEST_SKU });
    await expect(updatedRow.getByText("1200×800×3 мм")).toBeVisible({ timeout: 5_000 });

    // 17. Проверяем через API что dimensions сохранились
    const product = await apiGetProductBySku(TEST_SKU);
    const apiRes = await fetch(`${BACKEND_URL}/api/products?sku=${encodeURIComponent(TEST_SKU)}`);
    const body = await apiRes.json();
    const item = body.items.find((i: any) => i.sku === TEST_SKU);
    expect(item).toBeDefined();
    expect(item.dimensions).not.toBeNull();
    expect(item.dimensions.length_mm).toBe(1200);
    expect(item.dimensions.width_mm).toBe(800);
    expect(item.dimensions.thickness_mm).toBe(3);
  });
});
