import { expect, test } from "./fixtures";
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
 * @mobile (#344) — окна на телефоне: рамка ограничивает окно экраном, а
 * кнопки подтверждения достижимы.
 *
 * Проверяется не «окно открылось», а три свойства каркаса на 390×844:
 *
 * 1. окно не шире экрана — иначе часть формы и кнопки уезжают за правый край,
 *    а страница под окном не прокручивается (Radix блокирует прокрутку body);
 * 2. окно не выше экрана, а содержимое при нехватке места прокручивается
 *    внутри окна (без потолка высоты кнопки оказываются под нижним краем);
 * 3. «Сохранить» и «Аннулировать» достижимы: прокручены в кадр и видны.
 *
 * Путь — настоящий: журнал передач открывается кнопкой, окно «Управление
 * передачей» — кликом по строке журнала. Сетап — API (`full_route`: задания
 * пройдены, между участками есть передачи, то есть в журнале есть строка).
 *
 * Границы проверки. Здесь не проверяется перенос шапки экрана и колонки
 * таблицы — это #343. Окна-«шторки» (`h-screen`) сюда не входят: у них своя
 * полноэкранная раскладка.
 */

const VIEWPORT = MOBILE_USE.viewport;

/** Окно по имени заголовка: `DialogTitle` — единственный источник имени. */
function dialogByTitle(page: import("@playwright/test").Page, title: string) {
  return page
    .getByRole("dialog")
    .filter({ has: page.getByRole("heading", { name: title, exact: true }) });
}

test.describe("@mobile Окна на телефоне: потолок высоты и доступность кнопок (#344)", () => {
  test.beforeEach(async () => {
    await apiResetAll();
    await apiSeedData();
  });

  test("«Управление передачей» не шире экрана, прокручивается и отдаёт кнопки", async ({
    authenticatedPage,
  }) => {
    test.slow();
    const page = authenticatedPage;

    // Спека проверяет телефон: если метка яруса потеряется, падать надо здесь.
    expect(page.viewportSize()).toEqual(VIEWPORT);

    const token = await apiAccessTokenFromPage(page);
    expect(token).toBeTruthy();

    // 1. Свой артикул и маршрут склад → упаковка, остаток на складе.
    const sku = `E2E-MOB-DIALOG-${Date.now()}`;
    const product = await apiCreateBareProduct(sku);
    const raw = await apiGetSectionByCode("RAW_STOCK");
    const packing = await apiGetSectionByCode("PACKING");

    const route = await apiCreateRoute(`E2E-MOB-DIALOG-${Date.now()}`);
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
    await apiAddRemainder(product.id, raw.id, 100, "E2E #344: остаток для журнала передач", {
      length_mm: 2700,
    });

    // 2. Прогон по всему маршруту: передачи между участками записаны в журнал.
    const run = await apiRunDemoFullRoute(token, {
      stage_preset: "full_route",
      initial_quantity: "40",
      route_id: route.id,
      product_id: product.id,
      run_id: `e2e-mobile-dialogs-${Date.now()}`,
    });
    expect(run.stopped_at_stage).toBe("completed");

    // 3. UI: /transfers → «Журнал передач» → строка нашего артикула.
    await page.goto("/transfers");
    await expect(
      page.getByRole("heading", { name: "Передачи между ГХП", exact: true }),
    ).toBeVisible({ timeout: 10_000 });

    await page.getByRole("button", { name: "Журнал передач" }).click();
    const journal = dialogByTitle(page, "Журнал передач");
    await expect(journal).toBeVisible({ timeout: 10_000 });

    // Шторка журнала остаётся полноэкранной: потолок высоты из каркаса её не
    // подрезал (`max-h-screen` перекрывает умолчание), и она прижата к краям.
    const journalBox = await journal.boundingBox();
    expect(journalBox, "у шторки журнала есть габариты").not.toBeNull();
    expect(journalBox!.y, "шторка начинается от верхнего края").toBe(0);
    expect(Math.round(journalBox!.height), "шторка во всю высоту экрана").toBe(
      VIEWPORT.height,
    );
    expect(journalBox!.width, "ширина шторки").toBeLessThanOrEqual(VIEWPORT.width);

    const historyRow = journal.locator("tr", { hasText: sku }).first();
    await expect(historyRow, "строка передачи в журнале").toBeVisible({ timeout: 15_000 });
    // Клик по первой ячейке: середина широкой строки на телефоне уезжает за
    // край (журнал не прокручивается по горизонтали — это не его тикет).
    await historyRow.locator("td").first().click();

    // 4. Окно «Управление передачей» — предмет проверки.
    const dialog = dialogByTitle(page, "Управление передачей");
    await expect(dialog).toBeVisible({ timeout: 10_000 });

    // 5. Габариты: окно целиком в экране по обеим осям.
    const box = await dialog.boundingBox();
    expect(box, "окно имеет габариты").not.toBeNull();
    expect(box!.width, "ширина окна против ширины экрана").toBeLessThanOrEqual(VIEWPORT.width);
    expect(box!.x, "левый край окна не за экраном").toBeGreaterThanOrEqual(0);
    expect(box!.x + box!.width, "правый край окна не за экраном").toBeLessThanOrEqual(
      VIEWPORT.width,
    );
    expect(box!.y, "верхний край окна не за экраном").toBeGreaterThanOrEqual(0);
    expect(box!.y + box!.height, "нижний край окна не за экраном").toBeLessThanOrEqual(
      VIEWPORT.height,
    );

    // 6. Каркас: у окна есть потолок высоты и внутренняя прокрутка.
    const frame = await dialog.evaluate((el) => {
      const style = getComputedStyle(el);
      return {
        maxHeight: style.maxHeight,
        overflowY: style.overflowY,
        scrollHeight: el.scrollHeight,
        clientHeight: el.clientHeight,
        scrollWidth: el.scrollWidth,
        clientWidth: el.clientWidth,
      };
    });
    expect(frame.maxHeight, "потолок высоты у окна").not.toBe("none");
    expect(["auto", "scroll"], "внутренняя прокрутка окна").toContain(frame.overflowY);
    expect(frame.scrollWidth, "содержимое не шире окна").toBeLessThanOrEqual(
      frame.clientWidth,
    );

    // Содержимое, которому не хватило места, обязано прокручиваться, а не
    // обрезаться: прокрутка — проверяемое свойство, а не «должно быть».
    if (frame.scrollHeight > frame.clientHeight) {
      const scrolled = await dialog.evaluate((el) => {
        el.scrollTop = el.scrollHeight;
        return el.scrollTop;
      });
      expect(scrolled, "окно прокручивается вниз").toBeGreaterThan(0);
    }

    // 7. Кнопки достижимы: прокручены в кадр и видны в пределах экрана.
    for (const name of ["Аннулировать", "Сохранить"]) {
      const button = dialog.getByRole("button", { name });
      await button.scrollIntoViewIfNeeded();
      await expect(button, `кнопка «${name}» видна`).toBeVisible();
      const buttonBox = await button.boundingBox();
      expect(buttonBox, `у кнопки «${name}» есть габариты`).not.toBeNull();
      expect(buttonBox!.x, `«${name}» не за левым краем`).toBeGreaterThanOrEqual(0);
      expect(buttonBox!.x + buttonBox!.width, `«${name}» не за правым краем`).toBeLessThanOrEqual(
        VIEWPORT.width,
      );
      expect(buttonBox!.y, `«${name}» не за верхним краем`).toBeGreaterThanOrEqual(0);
      expect(buttonBox!.y + buttonBox!.height, `«${name}» не за нижним краем`).toBeLessThanOrEqual(
        VIEWPORT.height,
      );
    }
  });
});
