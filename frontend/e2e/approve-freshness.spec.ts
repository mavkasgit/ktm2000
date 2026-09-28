import type { Page } from "@playwright/test";

import {
  apiAddRemainder,
  apiApplyChangeSet,
  apiEnsureCatalogProduct,
  apiGetActiveTemplate,
  apiGetProductBySku,
  apiGetSectionByCode,
  apiResetAll,
  apiSimulatePlanImport,
} from "./api-helpers";
import { expect, test } from "./fixtures";
import { E2E_SKU, seedReferenceDataViaUI } from "./ui-helpers";

/**
 * @ui — СВЕЖЕСТЬ ПОСЛЕ УТВЕРЖДЕНИЯ: строка плана видна на «Контроле выполнения»
 * сразу, без перезагрузки страницы.
 *
 * Это регресс на конкретный баг: позиция утверждалась, но на `/execution` не
 * появлялась до F5. Причина — рассинхрон инвалидации: одиночное утверждение
 * сбрасывало ключ строк контроля, а массовое (как и импорт, удаление позиции и
 * назначение маршрута) — нет, и запись висела в кэше до истечения `staleTime`.
 *
 * ## Почему навигация кликами, а не `page.goto`
 *
 * `page.goto` — полная перезагрузка документа: она пересоздаёт `QueryClient`,
 * кэш пуст, и баг не воспроизводится. Навигация через `goto` всегда дала бы
 * здесь зелёный результат. Клик по сайдбару — это то, что делает оператор, и
 * именно он сохраняет кэш.
 *
 * ## Почему строка поиска не трогается
 *
 * Ввод в поиск меняет `queryKey` и сам вызывает новый запрос, то есть маскирует
 * кэш ровно так же, как `goto`. Поэтому строка ищется по `#<id>` в таблице без
 * фильтра — в тесте всё равно одна позиция.
 *
 * Сетап данных — через API, в кадре только действия UI: утверждение и переход.
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

/** Первый заход на «Контроль выполнения» кликом: заполняет кэш экрана. */
async function warmUpExecutionCache(page: Page) {
  await page.getByRole("link", { name: "Контроль выполнения" }).click();
  await expect(page.getByRole("heading", { name: "Контроль выполнения" })).toBeVisible({
    timeout: 15_000,
  });
}

test.describe("@ui Свежесть контроля выполнения после утверждения позиции", () => {
  test.beforeEach(async ({ page, loginAsAdmin }) => {
    await loginAsAdmin();
    // `reset-all` чистит и справочники импорта, поэтому порядок обязателен.
    await apiResetAll();
    await seedReferenceDataViaUI(page);
    await seedSinglePlannedPosition();
  });

  test("одиночное утверждение: строка появляется без перезагрузки", async ({ page }) => {
    test.slow();
    await warmUpExecutionCache(page);

    await page.getByRole("link", { name: "План", exact: true }).click();
    const row = page.locator('[id^="plan-position-"]').filter({
      has: page.getByRole("button", { name: "Утвердить" }),
    });
    await row.first().waitFor({ state: "visible", timeout: 15_000 });
    const positionId = Number.parseInt(
      (await row.first().getAttribute("id"))!.replace("plan-position-", ""),
      10,
    );

    await row.first().getByRole("button", { name: "Утвердить" }).click();
    const forceBtn = page.getByRole("button", { name: "Утвердить всё равно" });
    if (await forceBtn.isVisible().catch(() => false)) await forceBtn.click();
    await expect(page.getByText("Позиция утверждена", { exact: true })).toBeVisible({ timeout: 15_000 });

    await page.getByRole("link", { name: "Контроль выполнения" }).click();
    await expect(page.getByRole("heading", { name: "Контроль выполнения" })).toBeVisible({
      timeout: 15_000,
    });

    await expect(
      page.locator(`tr[data-row-key="${positionId}"]`).first(),
      `позиция #${positionId} утверждена, но на контроле выполнения не появилась без перезагрузки`,
    ).toBeVisible({ timeout: 15_000 });
  });

  test("массовое утверждение: строка появляется без перезагрузки", async ({ page }) => {
    test.slow();
    await warmUpExecutionCache(page);

    await page.getByRole("link", { name: "План", exact: true }).click();
    const row = page.locator('[id^="plan-position-"]').filter({
      has: page.getByRole("button", { name: "Утвердить" }),
    });
    await row.first().waitFor({ state: "visible", timeout: 15_000 });
    const positionId = Number.parseInt(
      (await row.first().getAttribute("id"))!.replace("plan-position-", ""),
      10,
    );

    // Групповой режим включается отдельной кнопкой: обработчик выбора позиции
    // передаётся только когда режим включён, клик по строке до этого ничего не
    // делает.
    await page.getByRole("button", { name: "Групповые операции" }).click();
    await row.first().click();
    await expect(page.getByText("Выбрано: 1").first()).toBeVisible({ timeout: 10_000 });

    // Кнопка группового утверждения соседствует со счётчиком «Выбрано: N» в
    // панели фильтров; у позиции кнопка с тем же текстом, поэтому берём именно её.
    const bulkApprove = page
      .locator("span", { hasText: /^Выбрано:/ })
      .locator('xpath=following-sibling::button[normalize-space()="Утвердить"]')
      .first();
    await expect(bulkApprove).toBeVisible({ timeout: 10_000 });
    await bulkApprove.click();
    await expect(page.getByText(/Массовое утверждение|Частичный успех/).first()).toBeVisible({
      timeout: 20_000,
    });

    await page.getByRole("link", { name: "Контроль выполнения" }).click();
    await expect(page.getByRole("heading", { name: "Контроль выполнения" })).toBeVisible({
      timeout: 15_000,
    });

    await expect(
      page.locator(`tr[data-row-key="${positionId}"]`).first(),
      `МАССОВОЕ утверждение позиции #${positionId}: на контроле выполнения строка не появилась без перезагрузки`,
    ).toBeVisible({ timeout: 15_000 });
  });
});
