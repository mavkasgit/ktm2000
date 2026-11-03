import type { Locator, Page } from "@playwright/test";

import { expect } from "./fixtures";
import { MOBILE_USE } from "./mobile-project.mjs";

/**
 * Геометрия телефонной таблицы (#343, #345): то, что проверяют оба экрана на
 * 390px — «Передачи» и доска участка.
 *
 * Проверяется не класс и не атрибут, а пиксели: закреплённая ячейка, уехавшая
 * за край кадра, для оператора ровно так же недоступна, как колонка до #343,
 * а `sticky`-класс ничего не гарантирует, если таблица под ним шире окна.
 *
 * Контракт строки (`stickyCells`, `swipeAcrossRow`) переехал сюда из спеки
 * доски, когда за ним пришла вторая страница: копия ассерта в каждом файле
 * означала бы, что «влезает в телефон» для двух таблиц значит разное.
 */

const VIEWPORT_WIDTH = MOBILE_USE.viewport.width;

/** Скролл-контейнер общего примитива `MobileScrollTable`. */
export function tableScroller(page: Page): Locator {
  return page.locator("[data-mobile-scroll-table]").first();
}

/** Есть ли что листать: таблица шире видимой области контейнера. */
export async function scrollMetrics(
  scroller: Locator,
): Promise<{ scrollWidth: number; clientWidth: number }> {
  return scroller.evaluate((el) => ({
    scrollWidth: el.scrollWidth,
    clientWidth: el.clientWidth,
  }));
}

/** Прокрутка контейнера по горизонтали: 0 — таблица стоит на месте. */
export function readScrollLeft(scroller: Locator): Promise<number> {
  return scroller.evaluate((el) => el.scrollLeft);
}

/**
 * Закреплённая ячейка обязана быть целиком в кадре телефона: половина
 * «Артикула» под краем — это та же недоступная колонка, что и до #343.
 * Допуск 0,5px — субпиксельная раскладка.
 */
export function expectInsideViewport(box: { x: number; width: number } | null, what: string) {
  expect(box, `${what}: геометрия посчитана (элемент отрисован)`).not.toBeNull();
  const { x, width } = box as { x: number; width: number };
  expect(x, `${what}: левый край в кадре`).toBeGreaterThanOrEqual(-0.5);
  expect(x + width, `${what}: правый край в кадре`).toBeLessThanOrEqual(VIEWPORT_WIDTH + 0.5);
}

/**
 * Перетаскивание мышью: браузер сам не листает overflow-контейнер мышью,
 * поэтому это ровно тот жест, который реализует примитив. Шаги дробим, чтобы
 * порог жеста (8px) был пройден не одним прыжком, как у настоящей руки.
 */
export async function dragTable(page: Page, fromX: number, y: number, dx: number) {
  const steps = 12;
  await page.mouse.move(fromX, y);
  await page.mouse.down();
  for (let i = 1; i <= steps; i += 1) {
    await page.mouse.move(fromX + (dx * i) / steps, y);
  }
  await page.mouse.up();
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
export const MIN_DRAG_STRIP_PX = 16;

type RowBox = { x: number; y: number; width: number; height: number };

/**
 * Довести строку в кадр по вертикали и обнулить горизонталь контейнера.
 *
 * Таблица прокручивается (`maxHeight: 70vh`), и у строки ниже экрана
 * координаты формально есть, а попадания мышью — нет; `scrollIntoViewIfNeeded`
 * содержимого мог подвинуть контейнер по горизонтали, поэтому `scrollLeft`
 * снова 0.
 * Без этой доводки один и тот же замер давал бы разные числа в зависимости от
 * того, что тест делал до него.
 */
export async function primeRowForMeasure(page: Page, row: Locator) {
  const scroller = tableScroller(page);
  await row.scrollIntoViewIfNeeded();
  await scroller.evaluate((el) => {
    el.scrollLeft = 0;
  });
}

/**
 * Геометрия закреплённых ячеек строки — один контракт для «Передач» и доски
 * участка, для строки задания и для шапки группы: обе целиком в кадре 390px,
 * не наезжают друг на друга и оставляют полосу прокручиваемой таблицы. В
 * сообщении о падении — измеренные ширины: «не сходится в кадр» без чисел
 * пришлось бы замерять заново.
 *
 * Контракт один на оба экрана намеренно: у разделённого рамка кадра
 * разъехалась бы, и «на телефоне помещается» значило бы разное для строки
 * передачи и для строки задания.
 *
 * До замера строку нужно довести в кадр (`primeRowForMeasure`): таблица
 * прокручивается по вертикали, и у строки ниже экрана координаты формально
 * есть, а попадание мышью — нет.
 */
export async function stickyCells(row: Locator, what: string) {
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
  // Область прокрутки в тексте падения тоже: спор «не влезло» решается
  // пикселями, а не памятью о чужом экране — область прокрутки зависит от
  // отступов страницы и у двух таблиц одинаковой не обязана быть.
  const { clientWidth } = await scrollMetrics(tableScroller(row.page()));

  expect(
    strip,
    `«Артикул» ${what} не заезжает под «Действия»: профиль ${profile.width.toFixed(1)}px, ` +
      `действия ${actions.width.toFixed(1)}px, полосы осталось ${strip.toFixed(1)}px ` +
      `(область прокрутки ${clientWidth.toFixed(1)}px)`,
  ).toBeGreaterThanOrEqual(MIN_DRAG_STRIP_PX);

  return { profileCell, actionsCell, profile, actions, strip };
}

/**
 * Свайп по полосе между закреплёнными колонками: жест мышью прокручивает
 * таблицу, а закреплённое стоит на месте — оператор не теряет, о каком
 * задании или передаче идёт речь.
 *
 * Правило одно для строки задания, шапки группы и строки передачи: там, где
 * содержимое «Действий» длиннее (кнопки группы, напечатанная причина), жест
 * исчезает первым делом.
 */
export async function swipeAcrossRow(page: Page, row: Locator, what: string) {
  const scroller = tableScroller(page);
  // Строка доводиться в кадр, а горизаль обнуляется: иначе мышь бьёт по
  // пустоте под экраном, и жест «не работает» не из-за свайпа, а из-за
  // координаты (см. `primeRowForMeasure`).
  await primeRowForMeasure(page, row);

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
