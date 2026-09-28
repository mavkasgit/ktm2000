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
 * @ui — ПОПОВЕР ФИЛЬТРА КОЛОНКИ: набор не роняет таблицу и не спрашивает сервер
 * на каждый символ.
 *
 * Регресс на исходный баг: текст в поповере колонки уезжал в `queryKey` без
 * паузы, поэтому серия нажатий давала серию запросов, а каждый новый ключ без
 * кеша переводил страницу в `isLoading` — `ExecutionPage` на нём возвращал
 * «Загрузка...» вместо дерева, вместе с открытым поповером и набранным текстом.
 * Состояние поиска при этом переживало размонтирование, и колонка оставалась
 * «скрыто» отфильтрованной текстом, который оператор уже не видел.
 *
 * Что проверяется (все три наблюдаемы, а не «страница обновилась»):
 *
 * 1. **Один запрос на серию нажатий.** Считаем реальные запросы к списку
 *    строк контроля с параметром `route_name` — на тот же текст, что введён.
 *    Без паузы их было бы по одному на символ.
 * 2. **Поповер не закрылся и фокус остался в поле.** Размонтирование страницы
 *    уносило поповер вместе с `Input`; проверка «поле всё ещё в фокусе и
 *    содержит текст» краснела бы на прежнем коде.
 * 3. **«Загрузка...» не появлялось.** Текст-заглушка видна оператору как
 *    провал страницы, и появление её на смене фильтра — тот же баг.
 *
 * Сетап — через API, в кадре только работа с поповером.
 */
const NORMAL_LENGTH_MM = 3000;

/** Часть URL запроса строк контроля, по которой считаем обращения к серверу. */
const EXECUTION_ROWS = "/production-planning/rows";

async function seedPlannedPosition() {
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

/**
 * Запросы к списку строк с текстом `needle` в `route_name`.
 *
 * Считаем только то, что относится к нашему набору: прочие ключи (панельный
 * поиск, первая загрузка страницы) в счётчик не попадают, иначе проверка
 * «один запрос» зависела бы от порядка прогрузки экрана.
 */
function collectRouteSearchRequests(page: Page, needle: string): string[] {
  const urls: string[] = [];
  page.on("request", (request) => {
    const url = new URL(request.url());
    if (!url.pathname.includes(EXECUTION_ROWS)) return;
    if (url.searchParams.get("route_name") === needle) urls.push(request.url());
  });
  return urls;
}

test.describe("@ui Попапер фильтра колонки: пауза и живой поповер", () => {
  test.beforeEach(async ({ page, loginAsAdmin }) => {
    await loginAsAdmin();
    // `reset-all` чистит и справочники импорта, поэтому порядок обязателен.
    await apiResetAll();
    await seedReferenceDataViaUI(page);
    await seedPlannedPosition();
  });

  test("набор в поповере не роняет таблицу и даёт один запрос", async ({ page }) => {
    const needle = "Стре";

    // Позиция видна на контроле только в активных статусах
    // (`_ACTIVE_POSITION_STATUSES` в `production_planning_rows.py`), а импорт
    // оставляет её в `draft` — поэтому сначала утверждаем её на плане.
    // Утверждение — бизнес-действие, значит идёт через UI, а не через API.
    await page.getByRole("link", { name: "План", exact: true }).click();
    await expect(page.getByRole("heading", { name: "План", exact: true })).toBeVisible({
      timeout: 15_000,
    });
    const planRow = page.locator('[id^="plan-position-"]').filter({
      has: page.getByRole("button", { name: "Утвердить" }),
    });
    await planRow.first().waitFor({ state: "visible", timeout: 15_000 });
    await planRow.first().getByRole("button", { name: "Утвердить" }).click();
    const forceBtn = page.getByRole("button", { name: "Утвердить всё равно" });
    if (await forceBtn.isVisible().catch(() => false)) await forceBtn.click();
    await expect(page.getByText("Позиция утверждена", { exact: true })).toBeVisible({ timeout: 15_000 });

    // Считаем запросы до похода на страницу: первая загрузка контроля с пустым
    // `route_name` в счётчик не попадает, но подписка должна быть готова.
    const requests = collectRouteSearchRequests(page, needle);

    // Клик по сайдбару, а не `goto`: `goto` пересоздал бы QueryClient, и кеша
    // не существовало бы — проверять было бы нечего.
    await page.getByRole("link", { name: "Контроль выполнения" }).click();
    await expect(page.getByRole("heading", { name: "Контроль выполнения" })).toBeVisible({
      timeout: 15_000,
    });
    await expect(page.locator("tr[data-row-key]").first()).toBeVisible({ timeout: 15_000 });

    // Колонка «Маршрут» скрыта на узких экранах (`hidden min-[820px]`), поэтому
    // поповер открывается на широком окне.
    await page.setViewportSize({ width: 1600, height: 1000 });
    const header = page.getByRole("button", { name: "Маршрут", exact: true });
    await header.click();
    const search = page.getByPlaceholder("Поиск...");
    await expect(search).toBeVisible({ timeout: 5_000 });

    // Серия нажатий с интервалом меньше паузы: 80 мс против 300 мс.
    await search.pressSequentially(needle, { delay: 80 });

    // Пауза отпускает запрос — и он один, с последним введённым текстом.
    await expect
      .poll(() => requests.length, { timeout: 10_000 })
      .toBeGreaterThanOrEqual(1);
    // Даём заведомо больше паузы: лишний запрос после неё означал бы, что
    // набор всё ещё едет по одному символу.
    await page.waitForTimeout(1_500);
    expect(
      requests,
      `набор «${needle}» дал ${requests.length} запросов вместо одного: пауза перед запросом в поповере не работает`,
    ).toHaveLength(1);
    expect(requests[0]).toContain(encodeURIComponent(needle));

    // Поповер жив: страница не размонтировалась, поле в фокусе и хранит текст.
    await expect(
      search,
      "поле поиска в поповере потеряло текст или фокус: страница размонтировалась вместе с поповером",
    ).toHaveValue(needle);
    await expect(search).toBeFocused();
    await expect(page.getByRole("button", { name: "Готово" })).toBeVisible();

    // Заглушка не показывалась ни разу за всю серию.
    await expect(page.getByText("Загрузка...")).toHaveCount(0);

    // И дерево на месте: таблица и шапка целы. Строк после фильтра может не
    // остаться ни одной — это честный ответ сервера на текст, которого нет в
    // сид-данных; проверять тут надо ровно одно, что размонтирования не было.
    // Прежний код на этом шаге гасил страницу целиком, и таблицы не существовало
    // бы вовсе.
    await expect(page.locator("table.execution-table")).toBeVisible();
    await expect(page.getByRole("columnheader", { name: "Маршрут" })).toBeVisible();
  });
});
