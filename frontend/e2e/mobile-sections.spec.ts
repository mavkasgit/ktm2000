import type { Page } from "@playwright/test";

import { expect, test } from "./fixtures";
import {
  apiAccessTokenFromPage,
  apiAddRemainder,
  apiAddRouteStep,
  apiCreateBareProduct,
  apiCreateRoute,
  apiGetSectionByCode,
  apiGetSections,
  apiResetAll,
  apiRunDemoFullRoute,
  apiSeedData,
} from "./api-helpers";
import { MOBILE_USE } from "./mobile-project.mjs";

/**
 * @mobile (#342) — «Участки» с телефона: доска открывается, участок
 * выбирается плиткой, строки заданий видны.
 *
 * Ярус `mobile` (окно 390×844, `isMobile`, `hasTouch`): при такой ширине доска
 * участка идёт не таблицей, а карточками (`useMediaQuery("(min-width: 768px)")`),
 * поэтому проверка идёт по атрибуту строки `data-task-id`, а не по `tr` —
 * он есть у строки в обеих ветках вёрстки.
 *
 * Сетап — API, как в остальных `@smoke`-спеках: свой артикул, свой маршрут
 * склад → упаковка, `stage_preset: "after_release"` (позиция запущена: задания
 * на участках созданы, ничего не двигалось). Выбор участка и чтение доски —
 * уже UI: это то, что проверяется.
 */

/** Плитка участка в списке «Выберите рабочий участок». */
function sectionTile(page: Page, name: string) {
  // Имя участка — начало доступного имени кнопки: за ним идут бейджи
  // «ОЖ: N ВР: N», поэтому совпадение не точное, а по началу строки.
  return page.getByRole("button", { name: new RegExp(`^${escapeRegExp(name)}`) });
}

function escapeRegExp(value: string): string {
  return value.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
}

test.describe("@mobile Участки на телефоне: выбор участка и доска (#342)", () => {
  test.beforeEach(async () => {
    await apiResetAll();
    await apiSeedData();
  });

  test("плитка участка открывает его доску с заданиями", async ({ authenticatedPage }) => {
    test.slow();
    const page = authenticatedPage;

    // Спека проверяет телефон: если метка яруса потеряется и она уйдёт в
    // десктопный проект, падать надо здесь, а не на вёрстке карточек.
    expect(page.viewportSize()).toEqual(MOBILE_USE.viewport);

    const token = await apiAccessTokenFromPage(page);
    expect(token).toBeTruthy();

    // 1. Свой артикул и маршрут: склад (транзит) → упаковка (production).
    const sku = `E2E-MOB-SECTION-${Date.now()}`;
    const product = await apiCreateBareProduct(sku);
    const raw = await apiGetSectionByCode("RAW_STOCK");

    const sections = (await apiGetSections()) as Array<{
      id: number;
      code: string;
      name: string;
      type: string;
      is_active: boolean;
    }>;
    // Плитки показывает только активный производственный участок — если
    // сид стенда поменяется, падать надо здесь, а не на «плитки нет».
    const packing = sections.find((section) => section.code === "PACKING");
    expect(packing, "участок PACKING в справочнике").toBeTruthy();
    expect(packing!.is_active, "PACKING активен").toBe(true);
    expect(packing!.type, "PACKING — производственный участок").toBe("production");

    const route = await apiCreateRoute(`E2E-MOB-SECTION-${Date.now()}`);
    await apiAddRouteStep(route.id, {
      sequence: 1,
      section_id: raw.id,
      operation_code: null,
      operation_name: "Выдача сырья",
      is_final: false,
      stage_kind: "transit",
      storage_section_id: raw.id,
    });
    await apiAddRouteStep(route.id, {
      sequence: 2,
      section_id: packing!.id,
      operation_code: null,
      operation_name: "Упаковка",
      is_final: true,
    });

    await apiAddRemainder(product.id, raw.id, 100, "E2E #342: остаток сырья для мобильной доски", {
      length_mm: 2700,
    });

    // 2. Позиция запущена: задания по обоим этапам созданы.
    const run = await apiRunDemoFullRoute(token, {
      stage_preset: "after_release",
      initial_quantity: "40",
      route_id: route.id,
      product_id: product.id,
      run_id: `e2e-mobile-sections-${Date.now()}`,
    });
    expect(run.stopped_at_stage).toBe("released");
    expect(run.shopfloor_section_urls).toContain(`/section-tasks/${packing!.id}`);

    // 3. UI: список участков → плитка упаковки → её доска.
    await page.goto("/section-tasks");
    await expect(page.getByRole("heading", { name: "Участки", exact: true })).toBeVisible({
      timeout: 10_000,
    });
    await expect(page.getByText("Выберите рабочий участок")).toBeVisible();

    const tile = sectionTile(page, packing!.name).first();
    await expect(tile, "плитка участка «Упаковка» в списке").toBeVisible({ timeout: 15_000 });
    await tile.click();

    // Участок выбран: плитка помечена, маршрут ведёт на его доску.
    await expect(tile).toHaveAttribute("aria-pressed", "true", { timeout: 10_000 });
    await expect(page).toHaveURL(new RegExp(`/section-tasks/${packing!.id}$`));

    // 4. Доска показывает задание этого артикула. Атрибут `data-task-id` есть
    //    и у строки таблицы, и у карточки мобильной ветки — проверка не
    //    зависит от того, чем доска рисует строку.
    const taskRow = page.locator("[data-task-id]").filter({ hasText: sku }).first();
    await expect(taskRow, "строка задания на доске участка").toBeVisible({ timeout: 15_000 });
    await expect(taskRow).toContainText(sku);
  });
});
