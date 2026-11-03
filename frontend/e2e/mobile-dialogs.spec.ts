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
 * кнопки подтверждения и кнопка закрытия достижимы.
 *
 * Проверяются не «окно открылось», а четыре свойства каркаса на 390×844:
 *
 * 1. окно не шире экрана — иначе часть формы и кнопки уезжают за правый край,
 *    а страница под окном не прокручивается (Radix блокирует прокрутку body);
 * 2. окно не выше экрана, а содержимое при нехватке места прокручивается
 *    внутри окна (без потолка высоты кнопки оказываются под нижним краем);
 * 3. «Сохранить» и «Аннулировать» достижимы: прокручены в кадр и видны;
 * 4. ✕ остаётся у верхнего края рамки при любой прокрутке тела и по ней можно
 *    попасть мышью.
 *
 * Свойство 4 проверяется на гарантированном переполнении: в тело окна
 * добавляется блок высотой с экран. Проверяется каркас, а не конкретное окно —
 * какое бы содержимое в него ни набралось, рамка ведёт себя одинаково, и
 * полагаться на то, что форма «Управления передачей» когда-нибудь не влезет,
 * нельзя: до этого добавления ветка «есть что прокручивать» не выполнялась
 * никогда, то есть прокрутка не была проверена ни разу.
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

/**
 * ✕ доступна тогда, когда тело окна прокручено (#344, ревью 6).
 *
 * `toBeVisible()` это свойство не проверяет: он требует ненулевых габаритов и
 * НЕ требует попадания в вьюпорт — кнопка, уехавшая на 500px выше верхнего
 * края, для Playwright «видима», а для оператора её нет. Поэтому геометрия:
 * ✕ целиком внутри экрана, прижата к верхнему краю рамки (иначе засчитался бы
 * любой случайный охват) и в её центр попадает хит-тест (под кнопкой не должно
 * быть узла, который перехватил бы клик).
 *
 * @returns координаты центра ✕ — чтобы следующим шагом по ним ударить мышью.
 */
async function expectCloseReachable(dialog: import("@playwright/test").Locator) {
  const close = dialog.getByRole("button", { name: "Закрыть", exact: true });

  // Прокрутку в спеке ставят программно (`el.scrollTop = scrollHeight`), а
  // событие `scroll` доставляется следующим кадром. Без ожидания геометрия
  // читалась бы ДО того, как каркас догнал прокрутку: в полном прогоне
  // 2026-11-03 так и вышло — ✕ на -546px, хотя каркас её двигает (#344).
  // Это не ослабление проверки: то же условие, но с бюджетом на доставку
  // события; если компенсация не сработает вовсе, poll упадёт по таймауту.
  await expect
    .poll(
      async () => {
        const current = await close.boundingBox();
        return current ? current.y : Number.NEGATIVE_INFINITY;
      },
      { message: "✕ догнала прокрутку и вернулась в кадр", timeout: 5_000 },
    )
    .toBeGreaterThanOrEqual(0);

  const box = await close.boundingBox();
  expect(box, "у ✕ есть габариты").not.toBeNull();
  const frameBox = await dialog.boundingBox();
  expect(frameBox, "у рамки есть габариты").not.toBeNull();

  expect(box!.y, "✕ не за верхним краем экрана").toBeGreaterThanOrEqual(0);
  expect(box!.y + box!.height, "✕ не за нижним краем экрана").toBeLessThanOrEqual(
    VIEWPORT.height,
  );
  expect(box!.x, "✕ не за левым краем экрана").toBeGreaterThanOrEqual(0);
  expect(box!.x + box!.width, "✕ не за правым краем экрана").toBeLessThanOrEqual(
    VIEWPORT.width,
  );
  // Рамка рисует ✕ на 1rem+поле от своего верхнего края; допуск 40px — это
  // поле `p-6` плюс строка заголовка: больше — значит кнопка отвалилась вниз
  // и висит над серединой формы.
  const inset = box!.y - frameBox!.y;
  expect(inset, "✕ не ушла выше верхнего края рамки").toBeGreaterThanOrEqual(0);
  expect(inset, "✕ прижата к верхнему краю рамки").toBeLessThan(40);

  const cx = box!.x + box!.width / 2;
  const cy = box!.y + box!.height / 2;
  const hit = await dialog.evaluate((el, point) => {
    const target = document.elementFromPoint(point.x, point.y);
    return !!target && target.closest('[role="dialog"]') === el;
  }, { x: cx, y: cy });
  expect(hit, "в точку под центром ✕ попадает хит-тест этой рамки").toBe(true);

  return { cx, cy };
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
    //
    // Это условие, а не утверждение, и само по себе оно ничего не доказывало:
    // у реального «Управления передачей» тела меньше, чем даёт потолок, поэтому
    // ветка не выполнялась никогда (#344, ревью 6). Ниже то же свойство
    // проверяется на переполнении, которое сконструировано.
    if (frame.scrollHeight > frame.clientHeight) {
      const scrolled = await dialog.evaluate((el) => {
        el.scrollTop = el.scrollHeight;
        return el.scrollTop;
      });
      expect(scrolled, "окно прокручивается вниз").toBeGreaterThan(0);
    }

    // 7. Переполнение, которое есть всегда (#344, ревью 6).
    //
    // Каркас проверяется на себе, а не на этом окне: какое бы тело ни оказалось
    // выше потолка, рамка обязана прокручивать его и держать кнопку закрытия в
    // кадре. Поэтому в тело добавляется блок высотой с экран — прокрутка
    // появляется гарантированно, и ни одна ветка не остаётся пропущенной.
    //
    // Габариты окна при этом не меняются: потолок высоты даёт рамка, а не
    // содержимое. Не держи потолок, проверка прокрутки была бы бессильна: окно
    // выросло бы за экран, и прокручивать в нём было бы нечего.
    const overflow = await dialog.evaluate((el, px) => {
      const spacer = document.createElement("div");
      spacer.style.height = `${px}px`;
      el.appendChild(spacer);
      return { scrollHeight: el.scrollHeight, clientHeight: el.clientHeight };
    }, VIEWPORT.height);
    expect(
      overflow.scrollHeight,
      "тела больше, чем помещается в окно",
    ).toBeGreaterThan(overflow.clientHeight);

    const clamped = await dialog.boundingBox();
    expect(clamped, "у окна есть габариты").not.toBeNull();
    expect(
      clamped!.y + clamped!.height,
      "окно не выросло за экран вместе с телом",
    ).toBeLessThanOrEqual(VIEWPORT.height);

    const scrolledTo = await dialog.evaluate((el) => {
      el.scrollTop = el.scrollHeight;
      return {
        scrollTop: el.scrollTop,
        scrollHeight: el.scrollHeight,
        clientHeight: el.clientHeight,
      };
    });
    expect(scrolledTo.scrollTop, "окно прокручивается вниз").toBeGreaterThan(0);
    expect(
      scrolledTo.scrollHeight - scrolledTo.scrollTop - scrolledTo.clientHeight,
      "прокрутка доведена до конца",
    ).toBeLessThanOrEqual(1);

    // 8. Тело прокручено до конца — ✕ всё ещё у верхнего края рамки.
    await expectCloseReachable(dialog);

    // 9. Кнопки достижимы: прокручены в кадр и видны в пределах экрана.
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

    // 10. Компенсация ✕ живёт ровно столько, сколько прокрутка: после
    // `scrollIntoViewIfNeeded` смещение рамки другое, и кнопка обязана
    // следовать за ним, а не остаться на позиции первой прокрутки.
    await expectCloseReachable(dialog);

    // 11. Доказательство доступности — не геометрия, а дело: клик ровно в
    // точку ✕ (без `scrollIntoView`, который подкрутил бы окно сам) закрывает
    // окно. На непрокрученном теле этот шаг тривиален, на прокрученном — нет.
    const { cx, cy } = await expectCloseReachable(dialog);
    await page.mouse.click(cx, cy);
    await expect(dialog, "окно закрылось кликом по ✕").toBeHidden({ timeout: 10_000 });
  });
});
