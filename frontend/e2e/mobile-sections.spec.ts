import type { Locator, Page } from "@playwright/test";

import { expect, test } from "./fixtures";
import {
  apiAccessTokenFromPage,
  apiAddRemainder,
  apiAddRouteStep,
  apiApplyChangeSet,
  apiApprovePosition,
  apiBatchAssignRoute,
  apiCreateBareProduct,
  apiCreateRoute,
  apiGetPlanPositions,
  apiGetSectionByCode,
  apiGetSections,
  apiResetAll,
  apiRunDemoFullRoute,
  apiSeedData,
  apiSimulatePlanImport,
  authHeaders,
  BACKEND_URL,
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
 * @mobile (#342, #345) — «Участки» с телефона: доска открывается, участок
 * выбирается плиткой, задание — строка общей таблицы.
 *
 * С #345 карточка задания заменена той же таблицей, что и «Передачи» (#343):
 * карточки остались только для выбора участка. Поэтому носитель строки здесь
 * `<tr>` на любой ширине, а `useMediaQuery("(min-width: 768px)")` меняет только
 * набор и порядок колонок. Проверяется не класс, а геометрия кадра 390×844:
 * закреплённые «Артикул» и «Действия» целиком в экране, не наезжают друг на
 * друга и оставляют полосу, по которой жест листает вторичные колонки — одно
 * правило для строки задания и для шапки группы, у которой кнопки длиннее. Поле
 * группового ввода (#283) доводится до кадра и принимает число.
 *
 * Сетап — API, как в остальных `@mobile`-спеках: свой артикул, свой маршрут
 * склад → упаковка, `stage_preset: "after_release"` (позиция запущена: задания
 * на участках созданы, движений материала нет). Группа одного артикула — двумя
 * позициями плана через импорт и релиз: шаги маршрута её не дают. Выбор участка
 * и работа с доской — уже UI: это то, что проверяется.
 *
 * Требует стенда E2E (`npm --prefix frontend run test:e2e:mobile`).
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

/**
 * Строка задания этого артикула. `data-row-kind` отделяет её от шапки группы:
 * у той тоже есть `data-sticky`, но задания она не вводит.
 */
function taskRow(page: Page, sku: string) {
  return page.locator('tr[data-row-kind="board-task"]').filter({ hasText: sku }).first();
}

/**
 * Справочник под доску: склад сырья и участок упаковки. Плитки показывает только
 * активный производственный участок — если сид стенда поменяется, падать надо
 * здесь, а не на «плитки нет».
 */
async function seedSections() {
  const raw = await apiGetSectionByCode("RAW_STOCK");

  const sections = (await apiGetSections()) as Array<{
    id: number;
    code: string;
    name: string;
    type: string;
    is_active: boolean;
  }>;
  const packing = sections.find((section) => section.code === "PACKING");
  expect(packing, "участок PACKING в справочнике").toBeTruthy();
  expect(packing!.is_active, "PACKING активен").toBe(true);
  expect(packing!.type, "PACKING — производственный участок").toBe("production");

  return { raw, packing: packing! };
}

/** Маршрут «склад → упаковка»: после релиза задание стоит на доске упаковки. */
async function seedPackingRoute(raw: { id: number }, packing: { id: number }) {
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
    section_id: packing.id,
    operation_code: null,
    operation_name: "Упаковка",
    is_final: true,
  });
  return route;
}

/**
 * Участок, артикул, маршрут и запущенная позиция: задание упаковки попадает на
 * доску `sectionId`. Артикул уникален на прогон — строка ищется по нему, а не
 * по порядку, и чужие строки стенда проверку не подменяют.
 */
async function seedPackingTask(token: string, sku: string) {
  const product = await apiCreateBareProduct(sku);
  const { raw, packing } = await seedSections();
  const route = await seedPackingRoute(raw, packing);

  await apiAddRemainder(product.id, raw.id, 100, "E2E #345: остаток сырья для мобильной доски", {
    length_mm: 2700,
  });

  const run = await apiRunDemoFullRoute(token, {
    stage_preset: "after_release",
    initial_quantity: "40",
    route_id: route.id,
    product_id: product.id,
    run_id: `e2e-mobile-sections-${Date.now()}`,
  });
  expect(run.stopped_at_stage).toBe("released");
  expect(run.shopfloor_section_urls).toContain(`/section-tasks/${packing.id}`);

  return packing;
}

/**
 * Релиз позиций плана без UI: батч только фиксирует позиции, задания на участках
 * создаёт `release`.
 */
async function apiReleasePlanPositions(planId: number, positionIds: number[]) {
  async function post(pathname: string, payload?: unknown) {
    const res = await fetch(`${BACKEND_URL}${pathname}`, {
      method: "POST",
      headers: await authHeaders({ "Content-Type": "application/json" }),
      body: payload ? JSON.stringify(payload) : undefined,
    });
    if (!res.ok) {
      throw new Error(`POST ${pathname} failed: ${res.status} ${await res.text()}`);
    }
    return res.json().catch(() => null);
  }

  const batch = (await post(`/api/production-plans/${planId}/release-batches`, {
    positions: positionIds.map((id) => ({ plan_position_id: id })),
  })) as { id: number };
  await post(`/api/release-batches/${batch.id}/release`);
}

/**
 * Группа одного артикула на доске упаковки: `size` позиций плана с одним SKU,
 * утверждённые и выпущенные по общему маршруту.
 *
 * Группа собирается именно позициями, а не шагами маршрута: релиз создаёт
 * задание только на первый производственный шаг, задания следующих шагов
 * появляются после передачи. Два шага на одном участке дали бы одно задание, и
 * шапки группы на доске не было бы.
 */
async function seedPackingGroup(sku: string, size: number) {
  const product = await apiCreateBareProduct(sku);
  const { raw, packing } = await seedSections();
  const route = await seedPackingRoute(raw, packing);

  await apiAddRemainder(
    product.id,
    raw.id,
    100 * size,
    "E2E #345: остаток сырья под группу одного артикула",
    { length_mm: 2700 },
  );

  // Строки различаются упаковкой: одинаковые выходы импорт сводит в одну
  // позицию, а нам нужно `size` отдельных запусков.
  const rows = Array.from({ length: size }, (_, index) => ({
    sku,
    name: `Кант универсальный 47мм 2,7 (${sku})`,
    raw_stock: 100,
    color: "серебро",
    qty_per_27: 40,
    length_m: 2.7,
    packaging: `Упаковка ${index}`,
    output_length_m: 2.7,
    output_qty: 40,
    west: 40,
    east: 0,
    kind: "ГП",
  }));
  const imported = await apiSimulatePlanImport(rows);
  await apiApplyChangeSet(imported.production_plan_id, imported.change_set_id);

  const positions = (await apiGetPlanPositions(imported.production_plan_id)) as Array<{
    id: number;
    source_sku: string;
    validation_status: string;
  }>;
  const ids = positions
    .filter((p) => p.source_sku === sku && p.validation_status === "valid")
    .map((p) => p.id);
  expect(
    ids,
    `план дал ${size} валидные позиции артикула ${sku}`,
  ).toHaveLength(size);

  await apiBatchAssignRoute(imported.production_plan_id, ids, route.id);
  for (const id of ids) {
    await apiApprovePosition(imported.production_plan_id, id);
  }
  await apiReleasePlanPositions(imported.production_plan_id, ids);

  return packing;
}

/** Список участков → плитка упаковки → её доска. */
async function openPackingBoard(page: Page, packing: { id: number; name: string }) {
  await page.goto("/section-tasks");
  await expect(page.getByRole("heading", { name: "Участки", exact: true })).toBeVisible({
    timeout: 10_000,
  });
  await expect(page.getByText("Выберите рабочий участок")).toBeVisible();

  const tile = sectionTile(page, packing.name).first();
  await expect(tile, "плитка участка «Упаковка» в списке").toBeVisible({ timeout: 15_000 });
  await tile.click();

  await expect(tile).toHaveAttribute("aria-pressed", "true", { timeout: 10_000 });
  await expect(page).toHaveURL(new RegExp(`/section-tasks/${packing.id}$`));
}

/**
 * Минимальная полоса между закреплёнными колонками: жест мышью начинается по
 * прокручиваемой таблице, и если обе липкие колонки съели кадр, вести его не по
 * чему — точкой жеста окажется либо кнопка, либо чужая закреплённая ячейка.
 *
 * 16px — не круглая цифра «на глаз»: полоса обязана быть вдвое длиннее порога
 * свайпа примитива (8px, `DRAG_THRESHOLD_PX` в `MobileScrollTable`), иначе
 * жест, начатый в ней, рисковал бы не набрать ход. Фактические ширины
 * закреплённых колонок попадают в сообщение о падении — если раскладка
 * поедет, полосы будут перед собой, а не «придётся замерять заново».
 */
const MIN_DRAG_STRIP_PX = 16;

type RowBox = { x: number; y: number; width: number; height: number };

/**
 * Геометрия закреплённых ячеек строки доски — один контракт для строки задания
 * и для шапки группы: обе целиком в кадре 390px, не наезжают друг на друга и
 * оставляют полосу прокручиваемой таблицы. В сообщении о падении — измеренные
 * ширины: «не сходится в кадр» без чисел пришлось бы замерять заново.
 *
 * Строку нужно довести в кадр по вертикали до замера: доска прокручивается
 * (`maxHeight: 70vh`), и у строки ниже экрана координаты формально есть, а
 * попадание мышью — нет.
 */
async function stickyCells(row: Locator, what: string) {
  const profileCell = row.locator('[data-sticky="profile"]');
  const actionsCell = row.locator('[data-sticky="actions"]');
  await expect(profileCell, `закреплённый «Артикул» ${what}`).toBeVisible();
  await expect(actionsCell, `закреплённые «Действия» ${what}`).toBeVisible();

  const profileBox = await profileCell.boundingBox();
  const actionsBox = await actionsCell.boundingBox();
  expectInsideViewport(profileBox, `закреплённый «Артикул» ${what}`);
  expectInsideViewport(actionsBox, `закреплённые «Действия» ${what}`);
  const profile = profileBox as RowBox;
  const actions = actionsBox as RowBox;
  const strip = actions.x - (profile.x + profile.width);

  expect(
    strip,
    `«Артикул» ${what} не заезжает под «Действия»: профиль ${profile.width.toFixed(1)}px, ` +
      `действия ${actions.width.toFixed(1)}px, полосы осталось ${strip.toFixed(1)}px`,
  ).toBeGreaterThanOrEqual(MIN_DRAG_STRIP_PX);

  return { profileCell, actionsCell, profile, actions, strip };
}

/**
 * Свайп по полосе между закреплёнными колонками: жест мышью прокручивает
 * таблицу, а закреплённое стоит на месте — оператор не теряет, о каком
 * задании идёт речь.
 *
 * Правило одно для строки задания и для шапки группы: у шапки кнопки длиннее,
 * и если обе липкие колонки съедают кадр, жест исчезает именно на ней.
 */
async function swipeAcrossRow(page: Page, row: Locator, what: string) {
  const scroller = tableScroller(page);
  // Доска прокручивается по вертикали (`maxHeight: 70vh`): без доводки строки
  // в кадр мышь бьёт по пустоте под экраном, и жест «не работает» не из-за
  // свайпа, а из-за координаты. Горизаль после доводки снова обнуляется.
  await row.scrollIntoViewIfNeeded();
  await scroller.evaluate((el) => {
    el.scrollLeft = 0;
  });

  const { profileCell, actionsCell, profile, actions, strip } = await stickyCells(row, what);
  const dragFromX = profile.x + profile.width + strip / 2;
  const dragY = profile.y + profile.height / 2;
  expect(
    dragY,
    `жест ${what} начинается внутри кадра телефона`,
  ).toBeLessThanOrEqual(MOBILE_USE.viewport.height);

  const scrollLeftBefore = await readScrollLeft(scroller);
  expect(scrollLeftBefore, `до жеста ${what} таблица не прокручена`).toBe(0);

  await dragTable(page, dragFromX, dragY, -120);

  const scrollLeftAfter = await readScrollLeft(scroller);
  expect(scrollLeftAfter, `перетаскивание мышью прокручивает ${what}`).toBeGreaterThan(50);

  const profileAfter = await profileCell.boundingBox();
  const actionsAfter = await actionsCell.boundingBox();
  expectInsideViewport(profileAfter, `${what}: «Артикул» после свайпа`);
  expectInsideViewport(actionsAfter, `${what}: «Действия» после свайпа`);
  expect(
    Math.abs((profileAfter as { x: number }).x - profile.x),
    `${what}: «Артикул» не сдвинулся при прокрутке`,
  ).toBeLessThanOrEqual(1);
  expect(
    Math.abs((actionsAfter as { x: number }).x - actions.x),
    `${what}: «Действия» не сдвинулись при прокрутке`,
  ).toBeLessThanOrEqual(1);
}

test.describe("@mobile Участки на телефоне: доска задания таблицей (#342, #345)", () => {
  test.beforeEach(async () => {
    await apiResetAll();
    await apiSeedData();
  });

  test("задание — строка таблицы: профиль и действия закреплены, остальное листается свайпом", async ({
    authenticatedPage,
  }) => {
    test.slow();
    const page = authenticatedPage;

    // Спека проверяет телефон: если метка яруса потеряется и она уйдёт в
    // десктопный проект, падать надо здесь, а не на вёрстке колонок.
    expect(page.viewportSize()).toEqual(MOBILE_USE.viewport);

    const token = await apiAccessTokenFromPage(page);
    expect(token).toBeTruthy();

    const sku = `E2E-MOB-SECTION-${Date.now()}`;
    const packing = await seedPackingTask(token, sku);
    await openPackingBoard(page, packing);

    // 1. Карточек задания больше нет (#345): строка — `<tr>` на обеих ширину.
    const row = taskRow(page, sku);
    await expect(row, "строка задания на доске участка").toBeVisible({ timeout: 15_000 });
    await expect(page.locator("div[data-task-id]"), "карточка задания не рисуется вторым слоем").toHaveCount(0);

    // 2. Таблица шире окна: вторичным колонкам есть куда уезжать под свайп.
    const scroller = tableScroller(page);
    await expect(scroller).toBeVisible();
    const metrics = await scrollMetrics(scroller);
    expect(metrics.scrollWidth, "таблица шире окна — есть что листать").toBeGreaterThan(
      metrics.clientWidth,
    );

    // 3–5. Закреплённые «Артикул» и «Действия» целиком в кадре, не наезжают
    //      друг на друга, между ними остаётся полоса — и по ней таблица
    //      листается мышью, не сдвигая закреплённое.
    await swipeAcrossRow(page, row, "строки задания");
  });

  test("группа заданий: шапка группы на телефоне листается так же, как строка", async ({
    authenticatedPage,
  }) => {
    test.slow();
    const page = authenticatedPage;
    expect(page.viewportSize()).toEqual(MOBILE_USE.viewport);

    // Две позиции одного артикула в запуске: на доске они группа. Её шапка — та
    // же таблица с теми же закреплёнными колонками, только кнопки в ней длиннее.
    const sku = `E2E-MOB-GROUP-${Date.now()}`;
    const packing = await seedPackingGroup(sku, 2);
    await openPackingBoard(page, packing);

    const header = page
      .locator('tr[data-row-kind="board-group"]')
      .filter({ hasText: sku })
      .first();
    await expect(header, "шапка группы на доске участка").toBeVisible({ timeout: 15_000 });

    // Группа из нескольких заданий по умолчанию свёрнута, а шеврон на телефоне
    // живёт в закреплённом «Артикуле» — тап по нему раскрывает группу и не
    // уезжает при прокрутке. Без раскрытия строк в группе не увидеть.
    await header.locator('[data-sticky="profile"]').click();
    await expect(
      page.locator('tr[data-row-kind="board-task"]').filter({ hasText: sku }),
      "группа раскрыта: в ней два задания",
    ).toHaveCount(2);

    await swipeAcrossRow(page, header, "шапки группы");
  });

  test("массовый ввод с телефона: тап по закреплённому артикулу выделяет строку, поле годных принимает число (#283)", async ({
    authenticatedPage,
  }) => {
    test.slow();
    const page = authenticatedPage;
    expect(page.viewportSize()).toEqual(MOBILE_USE.viewport);

    const token = await apiAccessTokenFromPage(page);
    expect(token).toBeTruthy();

    const sku = `E2E-MOB-BULK-${Date.now()}`;
    const packing = await seedPackingTask(token, sku);
    await openPackingBoard(page, packing);

    const row = taskRow(page, sku);
    await expect(row).toBeVisible({ timeout: 15_000 });

    const bulkToggle = page.getByRole("button", { name: "Групповые операции" });
    await expect(bulkToggle).toBeVisible();
    await bulkToggle.click();

    await expect(row).toHaveAttribute("aria-selected", "false", { timeout: 10_000 });

    // Тап по строке — по закреплённому профилю: он в кадре до любой прокрутки,
    // и это ровно тот палец, которым оператор выбирает задание.
    const profileCell = row.locator('[data-sticky="profile"]');
    await profileCell.click();
    await expect(row).toHaveAttribute("aria-selected", "true");

    // Инпуты живут у выделенной строки: поле появилось тем же тапом.
    const goodInput = page.getByLabel(`${sku}: годные`);
    await expect(goodInput).toHaveCount(1);
    await goodInput.scrollIntoViewIfNeeded();

    // Поле доводится до кадра и принимает число: `fill` без hit-target не
    // проходит, поэтому успешный ввод доказывает, что колонку не накрыло
    // закреплённой ячейкой.
    await expect(goodInput).toBeInViewport({ ratio: 1 });
    await expect(goodInput).toBeEditable();
    await goodInput.fill("3");
    await expect(goodInput).toHaveValue("3");

    // Профиль при этом остался на месте: строка не потеряла, о каком артикуле речь.
    expectInsideViewport(await profileCell.boundingBox(), "«Артикул» выделенной строки");
  });

  test("поиск сужает доску, «Сбросить» возвращает строку и снимает групповой режим", async ({
    authenticatedPage,
  }) => {
    test.slow();
    const page = authenticatedPage;
    expect(page.viewportSize()).toEqual(MOBILE_USE.viewport);

    const token = await apiAccessTokenFromPage(page);
    expect(token).toBeTruthy();

    const sku = `E2E-MOB-RESET-${Date.now()}`;
    const packing = await seedPackingTask(token, sku);
    await openPackingBoard(page, packing);

    const row = taskRow(page, sku);
    await expect(row).toBeVisible({ timeout: 15_000 });

    // Угол сброса фильтров на телефоне закрыт (он лёг бы под закреплённые
    // «Действия»), поэтому сброс живёт в ряду фильтров — и обязан быть рабочим.
    await page.getByRole("button", { name: "Групповые операции" }).click();
    await row.locator('[data-sticky="profile"]').click();
    await expect(row).toHaveAttribute("aria-selected", "true");

    const search = page.getByPlaceholder("Поиск", { exact: true });
    await search.scrollIntoViewIfNeeded();
    await search.fill("E2E-АРТИКУЛА-НЕТ");
    await expect(page.getByText("Нет заданий")).toBeVisible({ timeout: 15_000 });
    await expect(row).toHaveCount(0);

    await page.getByRole("button", { name: "Сбросить" }).click();

    // Строка вернулась, поле поиска пусто, активных фильтров не осталось.
    await expect(row).toBeVisible({ timeout: 15_000 });
    await expect(search).toHaveValue("");
    await expect(page.getByText("Активных фильтров")).toHaveCount(0);

    // Сброс снимает и групповой режим: выделенной строки нет, поле ввода тоже.
    await expect(page.getByLabel(`${sku}: годные`)).toHaveCount(0);
  });
});
