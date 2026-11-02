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
