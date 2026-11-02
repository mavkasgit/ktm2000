import { test, expect } from "./fixtures";
import {
  apiAccessTokenFromPage,
  apiAddRemainder,
  apiAddRouteStep,
  apiCreateBareProduct,
  apiCreateRoute,
  apiGetSectionByCode,
  apiResetAll,
  apiRunDemoFullRoute,
  apiSeedData,
} from "./api-helpers";
import { MOBILE_USE } from "./mobile-project.mjs";

/**
 * @mobile (#342) — «Передачи» с телефона: строка «Готово к передаче» даёт
 * поле количества и кнопку «Передать».
 *
 * Ярус `mobile` (проект `mobile`, окно 390×844, `isMobile`, `hasTouch`) — не
 * сужение десктопного окна: мобильные ветки вёрстки включаются по медиазапросу,
 * и спека проверяет то, ради чего они существуют, — оператор набирает
 * количество и отправляет передачу с телефона.
 *
 * Сетап — API: позиция плана не утверждается и не запускается через UI.
 * `stage_preset: "after_release"` останавливает демо-прогон на «позиция
 * запущена, заданий на участках есть, движений материала нет» — ровно то
 * состояние, в котором складская строка видна в «Готово к передаче». Дальше
 * демо-прогон идти нельзя: `full_route` отправляет материал и уводит строку.
 *
 * Проверяется не «страница открылась», а путь действия: поле принимает
 * число, кнопка отправки существует и доступна (не `disabled` — иначе
 * «доступна» было бы словом из тикета, а не свойством экрана).
 *
 * Границы проверки. Здесь не проверяется, что кнопка целиком влезает в окно
 * и попадает под палец — это #343 (закреплённые колонки и свайп таблицы).
 * Спека фиксирует, что элементы строки существуют, не заблокированы и
 * принимают ввод в мобильной ветке вёрстки; после #343 сюда добавляется
 * проверка попадания в кадр, а не вместо этой.
 *
 * Требует стенда E2E (`npm --prefix frontend run test:e2e:mobile`): адреса и
 * БД выдаёт обёртка прогона.
 */

test.describe("@mobile Передачи на телефоне: количество и «Передать» (#342)", () => {
  test.beforeEach(async () => {
    await apiResetAll();
    await apiSeedData();
  });

  test("строка «Готово к передаче» принимает количество и отдаёт «Передать»", async ({
    authenticatedPage,
  }) => {
    test.slow();
    const page = authenticatedPage;

    // Спека проверяет телефон: если она попадёт в десктопный проект (метка
    // яруса потерялась), падать надо здесь, а не на «странной» вёрстке.
    expect(page.viewportSize()).toEqual(MOBILE_USE.viewport);

    const token = await apiAccessTokenFromPage(page);
    expect(token).toBeTruthy();

    // 1. Свой артикул и свой маршрут: склад (транзит) → упаковка (production).
    //    Артикул уникален на прогон — строка в таблице ищется по нему, а не по
    //    порядку, и чужие строки стенда проверку не подменяют.
    const sku = `E2E-MOB-TRANSFER-${Date.now()}`;
    const product = await apiCreateBareProduct(sku);
    const raw = await apiGetSectionByCode("RAW_STOCK");
    const packing = await apiGetSectionByCode("PACKING");

    const route = await apiCreateRoute(`E2E-MOB-TRANSFER-${Date.now()}`);
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
      section_id: packing.id,
      operation_code: null,
      operation_name: "Упаковка",
      is_final: true,
    });

    // 2. Остаток на складе: без него бюджета строки нет и «Готово к передаче»
    //    останется пустым. Габарит — как у позиции плана (2,7 м), иначе
    //    складская строка не сойдётся с планом по размеру.
    await apiAddRemainder(product.id, raw.id, 100, "E2E #342: остаток сырья для мобильной передачи", {
      length_mm: 2700,
    });

    // 3. Позиция запущена: задания на участках созданы, материал ещё не двигался.
    const run = await apiRunDemoFullRoute(token, {
      stage_preset: "after_release",
      initial_quantity: "40",
      route_id: route.id,
      product_id: product.id,
      run_id: `e2e-mobile-transfers-${Date.now()}`,
    });
    expect(run.stopped_at_stage).toBe("released");
    expect(run.tasks_created).toBeGreaterThan(0);

    // 4. UI: /transfers — таблица «Готово к передаче» со строкой этого артикула.
    await page.goto("/transfers");
    await expect(
      page.getByRole("heading", { name: "Передачи между ГХП", exact: true }),
    ).toBeVisible({ timeout: 10_000 });

    // Две таблицы на экране различаются колонкой-признаком («К передаче» есть
    // только у готовых строк) — по ней и берём нужную.
    const readyTable = page
      .locator("table")
      .filter({ has: page.getByRole("columnheader").filter({ hasText: "К передаче" }) })
      .first();
    await expect(readyTable).toBeVisible({ timeout: 15_000 });

    const readyRow = readyTable.locator("tr", { hasText: sku }).first();
    await expect(readyRow, "строка артикула в «Готово к передаче»").toBeVisible({
      timeout: 15_000,
    });

    // 5. Количество вводится с телефона: поле доступно и принимает число.
    const qtyInput = readyRow.locator('input[type="number"]').first();
    await expect(qtyInput).toBeVisible();
    await expect(qtyInput).toBeEditable();
    await qtyInput.fill("5");
    await expect(qtyInput).toHaveValue("5");

    // 6. Кнопка отправки доступна: не спрятана, не заблокирована причиной.
    const transferButton = readyRow.getByRole("button", { name: "Передать" });
    await expect(transferButton).toBeVisible();
    await expect(transferButton).toBeEnabled();
  });
});
