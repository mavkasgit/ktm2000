import {
  apiApplyChangeSet,
  apiEnsureCatalogProduct,
  apiGetActiveTemplate,
  apiGetProductBySku,
  apiGetSectionByCode,
  apiAddRemainder,
  apiResetAll,
  apiSimulatePlanImport,
} from "./api-helpers";
import { expect, test } from "./fixtures";
import { E2E_SKU, seedReferenceDataViaUI } from "./ui-helpers";

/**
 * @smoke — Escape в массовом режиме плана принадлежит верхнему слою.
 *
 * Регресс на гонку фаз DOM: глобальный обработчик страницы и Radix слушают
 * `keydown` на разных узлах. В bubble-фазе окно уже закрыто (Radix снял
 * `data-state="open"`), и проверка «открыто ли окно» видит пустой DOM — страница
 * снимает массовый режим вместе с окном. Поэтому обработчик страницы слушает
 * capture-фазу (`window`, `true`), а `isAnyDialogOpen()` расширен на
 * `alertdialog`, меню, Select и Popover.
 *
 * Сценарий ровно тот, что проверял человек: выделили строки, открыли окно,
 * нажали Escape — окно закрылось, выделение осталось; второй Escape снимает
 * выделение. Тест в ярусе smoke, потому что проверяет общий каркас окон и
 * клавиш, а не доменный сценарий.
 */

const NORMAL_LENGTH_MM = 3000;

async function seedSinglePlannedPosition() {
  await apiEnsureCatalogProduct({
    sku: E2E_SKU,
    name: "Уголок 15*15",
    lengthsMm: [NORMAL_LENGTH_MM],
    rawLengthMm: 3050,
    perimeterMm: 60,
    mountWidthMm: 15,
  });
  const product = await apiGetProductBySku(E2E_SKU);
  const rawStock = await apiGetSectionByCode("RAW_STOCK");
  await apiAddRemainder(product.id, rawStock.id, 400, "E2E остаток 3000мм", {
    length_mm: NORMAL_LENGTH_MM,
  });

  const template = await apiGetActiveTemplate();
  const importRes = await apiSimulatePlanImport(
    [
      {
        sku: E2E_SKU,
        name: "Уголок 15*15",
        raw_stock: 400,
        color: "серебро",
        qty_per_27: 300,
        length_m: 3,
        packaging: "смотка спанбондом поштучно в пачке 10 штук",
        output_length_m: 3,
        output_qty: 300,
        west: 300,
        east: 0,
        kind: "П/ф",
      },
    ],
    { templateId: template.id },
  );
  await apiApplyChangeSet(importRes.production_plan_id, importRes.change_set_id);
}

test.describe("@smoke Escape в массовом режиме плана", () => {
  test.beforeEach(async ({ page, loginAsAdmin }) => {
    await loginAsAdmin();
    // `reset-all` чистит и справочники импорта, поэтому порядок обязателен.
    await apiResetAll();
    await seedReferenceDataViaUI(page);
    await seedSinglePlannedPosition();
  });

  test("окно забирает Escape, выделение остаётся; второй Escape снимает его", async ({
    page,
  }) => {
    test.slow();
    await page.getByRole("link", { name: "План", exact: true }).click();
    await expect(page.getByRole("heading", { name: "План", exact: true })).toBeVisible({
      timeout: 15_000,
    });

    const row = page.locator('[id^="plan-position-"]').first();
    await expect(row, "строка плана видна").toBeVisible({ timeout: 15_000 });

    // Входим в массовый режим и выделяем строку — состояние, которое обязано
    // пережить закрытие окна.
    await page.getByRole("button", { name: "Групповые операции" }).click();
    await row.click();
    const selected = page.getByText("Выбрано: 1").first();
    await expect(selected, "строка выделена").toBeVisible({ timeout: 10_000 });

    // Окно поверх массового режима: «Добавить файл» открывает ImportWizard.
    await page.getByRole("button", { name: "Добавить файл" }).click();
    const dialog = page.getByRole("dialog", { name: "Импорт производственного плана" });
    await expect(dialog, "окно импорта открылось").toBeVisible({ timeout: 10_000 });

    await page.keyboard.press("Escape");
    await expect(dialog, "Escape закрыл окно").toBeHidden({ timeout: 10_000 });
    await expect(
      selected,
      "закрытие окна не сняло массовый режим и выделение",
    ).toBeVisible({ timeout: 10_000 });

    // Второй Escape — теперь верхнего слоя нет, страница обрабатывает клавишу.
    await page.keyboard.press("Escape");
    await expect(
      page.getByText(/^Выбрано: \d+$/),
      "повторный Escape снял выделение",
    ).toHaveCount(0, { timeout: 10_000 });
  });
});
