import { test, expect, type Page } from "./fixtures";
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
import {
  dragTable,
  expectInsideViewport,
  readScrollLeft,
  scrollMetrics,
  tableScroller,
} from "./mobile-table-helpers";

/**
 * @mobile — «Передачи» с телефона.
 *
 * #342 — строка «Готово к передаче» даёт поле количества и кнопку «Передать»
 * (элементы существуют, принимают ввод и не заблокированы причиной).
 *
 * #343 — телефонная таблица: колонка «Артикул» закреплена слева, «Действия» —
 * справа, между ними таблица листается свайпом по всей поверхности. Спека
 * проверяет не классы, а геометрию: обе закреплённые ячейки целиком в кадре
 * 390px, поле количества и «Передать» видны до любой прокрутки, а
 * перетаскивание мышью меняет `scrollLeft`, не сдвигая закреплённые ячейки.
 * Шапка страницы на телефоне переносится (ГХП своей строкой, «Журнал» и
 * «Обновить» — следующей) и ничего не обрезает.
 *
 * Ярус `mobile` (проект `mobile`, окно 390×844, `isMobile`, `hasTouch`) — не
 * сужение десктопного окна: мобильные ветки вёрстки включаются по медиазапросу,
 * и спека проверяет то, ради чего они существуют.
 *
 * Сетап — API: позиция плана не утверждается и не запускается через UI.
 * `stage_preset: "after_release"` останавливает демо-прогон на «позиция
 * запущена, заданий на участках есть, движений материала нет» — ровно то
 * состояние, в котором складская строка видна в «Готово к передаче». Дальше
 * демо-прогон идти нельзя: `full_route` отправляет материал и уводит строку.
 * Второй тест, наоборот, доводит прогон до конца — там нужна финальная строка
 * с «Отправить», которая обязана оставаться вне группового режима.
 *
 * Требует стенда E2E (`npm --prefix frontend run test:e2e:mobile`): адреса и
 * БД выдаёт обёртка прогона.
 */

/** Готовая таблица: из двух таблиц её выдаёт колонка «К передаче». */
function readyTable(page: Page) {
  return page
    .locator("table")
    .filter({ has: page.getByRole("columnheader").filter({ hasText: "К передаче" }) })
    .first();
}

/**
 * Свой артикул и свой маршрут: склад (транзит) → упаковка (production, final).
 * Артикул уникален на прогон — строка ищется по нему, а не по порядку, и чужие
 * строки стенда проверку не подменяют.
 */
async function seedTransitRoute(sku: string) {
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

  // Остаток на складе: без него бюджета строки нет и «Готово к передаче»
  // останется пустым. Габарит — как у позиции плана (2,7 м), иначе складская
  // строка не сойдётся с планом по размеру.
  await apiAddRemainder(
    product.id,
    raw.id,
    100,
    "E2E #342/#343: остаток сырья для мобильной передачи",
    { length_mm: 2700 },
  );

  return { product, raw, packing, route };
}

test.describe("@mobile Передачи на телефоне: закреплённые колонки и свайп (#342, #343)", () => {
  test.beforeEach(async () => {
    await apiResetAll();
    await apiSeedData();
  });

  test("профиль и действия закреплены, таблица листается свайпом, поле и «Передать» в кадре", async ({
    authenticatedPage,
  }) => {
    test.slow();
    const page = authenticatedPage;

    // Спека проверяет телефон: если она попадёт в десктопный проект (метка
    // яруса потерялась), падать надо здесь, а не на «странной» вёрстке.
    expect(page.viewportSize()).toEqual(MOBILE_USE.viewport);

    const token = await apiAccessTokenFromPage(page);
    expect(token).toBeTruthy();

    // 1-3. Стенд: свой маршрут, остаток и запущенная позиция без движений.
    const sku = `E2E-MOB-TRANSFER-${Date.now()}`;
    const { product, route } = await seedTransitRoute(sku);

    const run = await apiRunDemoFullRoute(token, {
      stage_preset: "after_release",
      initial_quantity: "40",
      route_id: route.id,
      product_id: product.id,
      run_id: `e2e-mobile-transfers-${Date.now()}`,
    });
    expect(run.stopped_at_stage).toBe("released");
    expect(run.tasks_created).toBeGreaterThan(0);

    // 4. UI: /transfers — готовая таблица со строкой этого артикула.
    await page.goto("/transfers");
    await expect(
      page.getByRole("heading", { name: "Передачи между ГХП", exact: true }),
    ).toBeVisible({ timeout: 10_000 });

    const table = readyTable(page);
    await expect(table).toBeVisible({ timeout: 15_000 });

    const readyRow = table.locator("tr", { hasText: sku }).first();
    await expect(readyRow, "строка артикула в «Готово к передаче»").toBeVisible({
      timeout: 15_000,
    });

    // 5. Количество вводится с телефона: поле доступно и принимает число.
    const qtyInput = readyRow.locator('input[type="number"]').first();
    await expect(qtyInput).toBeEditable();
    await qtyInput.fill("5");
    await expect(qtyInput).toHaveValue("5");

    // 6. Кнопка отправки доступна: не спрятана, не заблокирована причиной.
    const transferButton = readyRow.getByRole("button", { name: "Передать" });
    await expect(transferButton).toBeEnabled();

    // 7. Таблица шире окна телефона — свайпу есть что прокручивать. Без
    //    минимальной ширины семь колонок сжимались в 320px и переполнения не
    //    возникало вовсе.
    const scroller = tableScroller(page);
    await expect(scroller).toBeVisible();
    const metrics = await scrollMetrics(scroller);
    expect(metrics.scrollWidth, "таблица шире окна — есть что листать").toBeGreaterThan(
      metrics.clientWidth,
    );

    // 8. Строка в кадре: горизонтальное перетаскивание меряем по её ячейкам.
    const profileCell = readyRow.locator('[data-sticky="profile"]');
    const actionsCell = readyRow.locator('[data-sticky="actions"]');
    await expect(profileCell).toBeVisible();
    await expect(actionsCell).toBeVisible();
    await qtyInput.scrollIntoViewIfNeeded();
    // `scrollIntoViewIfNeeded` мог подвинуть контейнер по горизонтали —
    // начинаем жест с нуля, чтобы геометрия была предсказуемой.
    await scroller.evaluate((el) => {
      el.scrollLeft = 0;
    });

    const profileBox = await profileCell.boundingBox();
    const actionsBox = await actionsCell.boundingBox();
    expectInsideViewport(profileBox, "закреплённый «Артикул» (профиль)");
    expectInsideViewport(actionsBox, "закреплённые «Действия»");
    const profile = profileBox as { x: number; width: number; y: number; height: number };
    const actions = actionsBox as { x: number; width: number; y: number; height: number };
    expect(
      profile.x + profile.width,
      "закреплённый «Артикул» не заезжает под «Действия»",
    ).toBeLessThanOrEqual(actions.x + 0.5);

    // 9. Поле количества, «передано/план» и «Передать» видны целиком до
    //    прокрутки: это и есть смысл закреплённых «Действий».
    const planLabel = readyRow.getByTitle("Уже передано / план задания").first();
    await expect(qtyInput).toBeInViewport({ ratio: 1 });
    await expect(planLabel).toBeInViewport({ ratio: 1 });
    await expect(transferButton).toBeInViewport({ ratio: 1 });

    // 10. Свайп по всей поверхности: жест начинается между закреплёнными
    //     ячейками (там лежит обычная прокручиваемая ячейка), а не в поле
    //     ввода и не в кнопке.
    const gapLeft = profile.x + profile.width;
    const gapRight = actions.x;
    const dragFromX = gapRight - gapLeft >= 4 ? (gapLeft + gapRight) / 2 : actions.x + 8;
    const dragY = profile.y + profile.height / 2;

    const scrollLeftBefore = await readScrollLeft(scroller);
    expect(scrollLeftBefore, "до жеста таблица не прокручена").toBe(0);

    await dragTable(page, dragFromX, dragY, -120);

    const scrollLeftAfter = await readScrollLeft(scroller);
    expect(scrollLeftAfter, "перетаскивание мышью прокручивает таблицу влево").toBeGreaterThan(
      50,
    );

    // 11. Закреплённые ячейки при этом стоят на месте: «Артикул» у левого
    //     края, «Действия» у правого, поле и кнопка по-прежнему в кадре.
    const profileAfter = await profileCell.boundingBox();
    const actionsAfter = await actionsCell.boundingBox();
    expectInsideViewport(profileAfter, "«Артикул» после свайпа");
    expectInsideViewport(actionsAfter, "«Действия» после свайпа");
    expect(
      Math.abs((profileAfter as { x: number }).x - profile.x),
      "«Артикул» не сдвинулся при прокрутке",
    ).toBeLessThanOrEqual(1);
    expect(
      Math.abs((actionsAfter as { x: number }).x - actions.x),
      "«Действия» не сдвинулись при прокрутке",
    ).toBeLessThanOrEqual(1);
    await expect(qtyInput).toBeInViewport({ ratio: 1 });
    await expect(transferButton).toBeInViewport({ ratio: 1 });

    // 12. Шапка страницы на телефоне переносится, а не обрезается: ГХП
    //     занимает свою строку, «Журнал передач» и «Обновить» уходят под неё,
    //     и всё это целиком в кадре.
    const pageHeader = page.locator("header.page-header");
    const spgSelect = pageHeader.getByRole("combobox").first();
    const journalButton = pageHeader.getByRole("button", { name: "Журнал передач" });
    const refreshButton = pageHeader.getByRole("button", { name: "Обновить" });
    await expect(spgSelect).toBeVisible();
    await expect(journalButton).toBeVisible();
    await expect(refreshButton).toBeVisible();

    const spgBox = (await spgSelect.boundingBox()) as {
      x: number;
      width: number;
      y: number;
      height: number;
    };
    const journalBox = (await journalButton.boundingBox()) as {
      x: number;
      width: number;
      y: number;
      height: number;
    };
    const refreshBox = (await refreshButton.boundingBox()) as {
      x: number;
      width: number;
      y: number;
      height: number;
    };
    expectInsideViewport(spgBox, "селект ГХП");
    expectInsideViewport(journalBox, "«Журнал передач»");
    expectInsideViewport(refreshBox, "«Обновить»");
    expect(spgBox.width, "селект ГХП занимает строку целиком").toBeGreaterThan(300);
    expect(
      journalBox.y,
      "«Журнал передач» переносится под селект ГХП",
    ).toBeGreaterThanOrEqual(spgBox.y + spgBox.height - 0.5);
    expect(
      Math.abs(journalBox.y - refreshBox.y),
      "«Журнал передач» и «Обновить» стоят в одной строке",
    ).toBeLessThanOrEqual(1);

    // 13. Поиск и «Фильтры» под перенесённой шапкой не ломаются: оба
    //     элемента видны целиком.
    const searchInput = page.getByPlaceholder("Поиск по ID, артикулу, этапу…");
    const bulkToggle = page.getByRole("button", { name: "Групповые операции" });
    await expect(searchInput).toBeVisible();
    await expect(bulkToggle).toBeVisible();
    await searchInput.scrollIntoViewIfNeeded();
    await expect(searchInput).toBeInViewport({ ratio: 1 });
    await expect(bulkToggle).toBeInViewport({ ratio: 1 });
  });

  test("финальная строка держит «Отправить» на телефоне и не уходит в групповой режим", async ({
    authenticatedPage,
  }) => {
    test.slow();
    const page = authenticatedPage;
    expect(page.viewportSize()).toEqual(MOBILE_USE.viewport);

    const token = await apiAccessTokenFromPage(page);
    expect(token).toBeTruthy();

    const sku = `E2E-MOB-FINAL-${Date.now()}`;
    const { product, route } = await seedTransitRoute(sku);

    // Прогон до конца: задача на PACKING завершена, но не выпущена — ровно
    // финальная строка «Готово к передаче».
    const run = await apiRunDemoFullRoute(token, {
      initial_quantity: "40",
      route_id: route.id,
      product_id: product.id,
      run_id: `e2e-mobile-final-${Date.now()}`,
    });
    expect(run.stopped_at_stage).toBe("completed");

    await page.goto("/transfers");
    await expect(
      page.getByRole("heading", { name: "Передачи между ГХП", exact: true }),
    ).toBeVisible({ timeout: 10_000 });

    const table = readyTable(page);
    await expect(table).toBeVisible({ timeout: 15_000 });
    const readyRow = table.locator("tr", { hasText: sku }).first();
    await expect(readyRow, "финальная строка артикула").toBeVisible({ timeout: 15_000 });

    // Финальная строка: «Отправить» вместо «Передать», и кнопка целиком в
    // кадре телефона (закреплённые «Действия»).
    const sendButton = readyRow.getByRole("button", { name: "Отправить" });
    await expect(sendButton).toBeVisible();
    await expect(readyRow.getByRole("button", { name: "Передать" })).toHaveCount(0);
    await sendButton.scrollIntoViewIfNeeded();
    await expect(sendButton).toBeInViewport({ ratio: 1 });

    // Массовый режим: финальный выпуск в групповую передачу не берётся —
    // кнопка остаётся на месте, но погашена, а поля количества у строки нет
    // (футер собирает только выбираемые строки).
    const bulkToggle = page.getByRole("button", { name: "Групповые операции" });
    await expect(bulkToggle).toBeVisible();
    await bulkToggle.click();

    await expect(sendButton).toBeVisible();
    await expect(sendButton).toBeDisabled();
    await expect(readyRow.locator('input[type="number"]')).toHaveCount(0);
    await expect(sendButton).toBeInViewport({ ratio: 1 });
  });
});
