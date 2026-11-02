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
  expectInsideViewport,
  primeRowForMeasure,
  scrollMetrics,
  stickyCells,
  swipeAcrossRow,
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
 * Контракт строки один на два экрана и живёт в `mobile-table-helpers.ts`
 * (`stickyCells`, `swipeAcrossRow`): между закреплёнными колонками обязана
 * остаться полоса прокрутки, а измеренные ширины уходят в текст падения.
 *
 * Ревью #341 (п. 2): самое широкое содержимое «Действий» — не доступная кнопка,
 * а погашенная с напечатанной причиной («Укажите количество», #193). Отдельный
 * тест ставит строку ровно в это состояние и меряет кадр целиком.
 *
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

    // 8. Один контракт с доской участка (#345): закреплённые «Артикул» и
    //    «Действия» целиком в кадре 390px, не наезжают друг на друга и
    //    оставляют полосу прокручиваемой таблицы. Измеренные ширины попадают в
    //    сообщение о падении — «не влезло» без чисел замерять заново.
    await primeRowForMeasure(page, readyRow);
    await stickyCells(readyRow, "строки «Передать»");

    // 9. Поле количества, «передано/план» и «Передать» видны целиком до
    //    прокрутки: это и есть смысл закреплённых «Действий».
    const planLabel = readyRow.getByTitle("Уже передано / план задания").first();
    await expect(qtyInput).toBeInViewport({ ratio: 1 });
    await expect(planLabel).toBeInViewport({ ratio: 1 });
    await expect(transferButton).toBeInViewport({ ratio: 1 });

    // 10–11. Свайп по полосе между закреплёнными колонками: жест мышью
    //        прокручивает таблицу (порог 8px набирается дробными шагами), а
    //        закреплённые ячейки стоят на месте — оператор не теряет, о какой
    //        передаче речь, и поле с кнопкой остаются в кадре.
    await swipeAcrossRow(page, readyRow, "строки «Передать»");
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

  test("строка без количества: причина напечатана и закреплённые «Действия» с ней влезают в 390px", async ({
    authenticatedPage,
  }) => {
    test.slow();
    const page = authenticatedPage;
    expect(page.viewportSize()).toEqual(MOBILE_USE.viewport);

    const token = await apiAccessTokenFromPage(page);
    expect(token).toBeTruthy();

    const sku = `E2E-MOB-REASON-${Date.now()}`;
    const { product, route } = await seedTransitRoute(sku);
    const run = await apiRunDemoFullRoute(token, {
      stage_preset: "after_release",
      initial_quantity: "40",
      route_id: route.id,
      product_id: product.id,
      run_id: `e2e-mobile-transfers-reason-${Date.now()}`,
    });
    expect(run.stopped_at_stage).toBe("released");

    await page.goto("/transfers");
    const table = readyTable(page);
    await expect(table).toBeVisible({ timeout: 15_000 });
    const readyRow = table.locator("tr", { hasText: sku }).first();
    await expect(readyRow, "строка артикула в «Готово к передаче»").toBeVisible({
      timeout: 15_000,
    });

    // Состояние «нечего передавать»: оператор обнулил количество. Кнопка
    // гаснет, и причина обязана быть напечатана рядом (#193) — на сенсорном
    // экране `title` не читается, а без слова рядом оператор не понял бы, что
    // кнопка сломалась.
    const qtyInput = readyRow.locator('input[type="number"]').first();
    await qtyInput.fill("0");
    const transferButton = readyRow.getByRole("button", { name: "Передать" });
    await expect(transferButton).toBeDisabled();
    const reason = readyRow.getByText("Укажите количество", { exact: true });
    await expect(reason, "причина недоступности напечатана текстом (#193)").toBeVisible();

    // Та же строка в том же контракте, что доска участка (#345): обе
    // закреплённые ячейки целиком в кадре 390px и между ними остаётся полоса
    // прокрутки. Измеренные ширины — в тексте падения: «Действия» с текстом
    // причины шире обычной строки, и если кадр разъехался, числа нужны сразу.
    await primeRowForMeasure(page, readyRow);
    const { actions } = await stickyCells(readyRow, "строки с напечатанной причиной");

    // Текст причины не съехался за край и не обрезан: целиком в кадре и
    // целиком внутри закреплённой ячейки. #193 запрещает прятать причину в
    // подсказку, а «Укажите…» с многоточием — ровно то же самое.
    await expect(reason).toBeInViewport({ ratio: 1 });
    const reasonBox = (await reason.boundingBox()) as {
      x: number;
      width: number;
      y: number;
      height: number;
    };
    expectInsideViewport(reasonBox, "напечатанная причина строки");
    expect(
      reasonBox.x + reasonBox.width,
      `причина не вылезла за границы закреплённых «Действий»: ячейка ${actions.width.toFixed(
        1,
      )}px, текст кончается на ${(reasonBox.x + reasonBox.width).toFixed(1)}px, ` +
        `правый край ячейки ${(actions.x + actions.width).toFixed(1)}px`,
    ).toBeLessThanOrEqual(actions.x + actions.width + 0.5);
    const clipped = await reason.evaluate((el) => el.scrollWidth - el.clientWidth);
    expect(clipped, "текст причины не срезан переполнением").toBeLessThanOrEqual(1);

    // Свайп по полосе остаётся: количество и кнопка с причиной не уезжают, а
    // вторичные колонки листаются.
    await swipeAcrossRow(page, readyRow, "строки с напечатанной причиной");
    await expect(qtyInput).toBeInViewport({ ratio: 1 });
    await expect(transferButton).toBeInViewport({ ratio: 1 });
    await expect(reason).toBeInViewport({ ratio: 1 });
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
