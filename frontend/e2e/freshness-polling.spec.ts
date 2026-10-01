import type { Page } from "@playwright/test";

import {
  apiAddRemainder,
  apiApprovePosition,
  apiApplyChangeSet,
  apiEnsureCatalogProduct,
  apiGetActiveTemplate,
  apiGetPlanPositions,
  apiGetProductBySku,
  apiGetSectionByCode,
  apiResetAll,
  apiSimulatePlanImport,
} from "./api-helpers";
import { expect, test } from "./fixtures";
import { E2E_SKU, seedReferenceDataViaUI } from "./ui-helpers";

/**
 * @ui — «ЧУЖИЕ ДЕЙСТВИЯ ВИДНЫ БЕЗ F5» (фаза 2 свежести, #206).
 *
 * Правило ADR-0041: изменений на экране, которые сделал другой терминал, клиент
 * сам не видит — реестр `invalidateDomains` срабатывает только на СВОЁ действие.
 * Фаза 2 закрывает ровно этот узкий случай опросом операционных экранов
 * («Контроль выполнения» — строки в работе) через `refetchInterval` 12 с, пока
 * вкладка в фокусе.
 *
 * ## Почему мутация идёт мимо вкладки
 *
 * «Коллега» здесь — прямой вызов API из Node другим токеном (`apiApprovePosition`),
 * а не клик на той же странице: клик по кнопке сбросил бы кэш через
 * `invalidateAfter`, и тест не отличил бы опрос от инвалидации. Экран открыт,
 * из него НИЧЕГО не делается, `page.goto` после этого не вызывается
 * (`goto` пересоздал бы QueryClient и обнулил кэш). Строка может появиться
 * только потому, что таймер опроса сам перечитал `production-planning/rows`.
 *
 * ## Почему вторая вкладка — отдельный тест
 *
 * Кэш у вкладок свой (два экземпляра приложения), и опрос обязан идти в каждой
 * вкладке независимо — тот же вывод, что у замера #208: цена терминала
 * умножается на число вкладок.
 *
 * Сетап — через API (без xlsx), в кадре только ожидание опроса.
 */

const NORMAL_LENGTH_MM = 3000;

/** Плановый сетап: одна черновая позиция, которую «коллега» утвердит извне. */
async function seedDraftPosition(): Promise<{ planId: number; positionId: number }> {
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

  const positions = (await apiGetPlanPositions(importRes.production_plan_id)) as Array<{ id: number }>;
  expect(positions, "позиция плана не создалась").toHaveLength(1);
  return { planId: importRes.production_plan_id, positionId: positions[0].id };
}

/** Открыть «Контроль выполнения» и убедиться, что позиции на экране ещё нет. */
async function openExecutionWithoutRow(page: Page, positionId: number) {
  await page.goto("/execution");
  await expect(page.getByRole("heading", { name: "Контроль выполнения" })).toBeVisible({
    timeout: 15_000,
  });
  await expect(
    page.locator(`tr[data-row-key="${positionId}"]`),
    `позиция #${positionId} уже видна до действия коллеги — тест не про опрос`,
  ).toHaveCount(0);
}

test.describe("@ui Опрос операционного экрана: чужие действия без F5", () => {
  test.beforeEach(async ({ page, loginAsAdmin }) => {
    await loginAsAdmin();
    await apiResetAll();
    await seedReferenceDataViaUI(page);
  });

  test("утверждение извне: строка появляется на открытом экране без перезагрузки", async ({
    page,
  }) => {
    test.slow();
    const { planId, positionId } = await seedDraftPosition();
    await openExecutionWithoutRow(page, positionId);

    // «Действие коллеги» — другой токен, другой контекст, UI не участвует.
    await apiApprovePosition(planId, positionId);

    // Перезагрузки нет: строка может приехать только таймером опроса ≤ 12 с.
    await expect(
      page.locator(`tr[data-row-key="${positionId}"]`).first(),
      `позиция #${positionId} утверждена извне, но открытый экран её не перечитал`,
    ).toBeVisible({ timeout: 25_000 });
  });

  test("две вкладки одного пользователя: изменение видит вторая вкладка", async ({ page }) => {
    test.slow();
    const { planId, positionId } = await seedDraftPosition();
    await openExecutionWithoutRow(page, positionId);

    // Вторая вкладка того же контекста: cookies/localStorage общие, кэш — свой.
    const second = await page.context().newPage();
    try {
      await openExecutionWithoutRow(second, positionId);

      await apiApprovePosition(planId, positionId);

      await expect(
        second.locator(`tr[data-row-key="${positionId}"]`).first(),
        `вторая вкладка не увидела утверждение извне без перезагрузки`,
      ).toBeVisible({ timeout: 25_000 });
    } finally {
      await second.close();
    }
  });
});
