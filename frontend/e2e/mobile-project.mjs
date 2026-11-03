/**
 * Мобильный ярус E2E (#342) — цифры окна и отчёт прогона.
 *
 * Зачем отдельный модуль. Мобильный проект Playwright отличается от прочих
 * не тегами, а **окном браузера**: `=== ярус mobile: Ns, код 0 ===` не
 * говорит, шёл ли прогон на телефоне или на суженном десктопе. Поэтому
 * `run-tier.mjs` печатает окно и список `@mobile`-спеков сам, а цифры берёт
 * отсюда — из того же объекта, который `playwright.config.ts` кладёт в
 * `use` проекта. Две копии цифр в конфиге и в отчёте дали бы отчёт
 * «390×844» при проекте на 1280×720, то есть зелёный прогон, доказывающий
 * не то, что заявлено.
 *
 * Почему `.mjs`, а не `.ts`: модуль читают оба — конфиг Playwright (TS) и
 * `run-tier.mjs` (скрипт запуска прогона). Тесты — `mobile-project.test.ts`.
 *
 * Здесь и ярусный словарь тегов (`tagRe`): `playwright.config.ts` берёт его от
 * сюда же, чтобы отбор спеков в ярус и их список в отчёте не разъехались.
 */

/** Имя проекта: `--project mobile`, `VALID_TIERS` в `run-tier.mjs`. */
export const MOBILE_PROJECT = "mobile";

/** Тег спеков яруса. Уходит в `grep` проекта и в `grepInvert` десктопных. */
export const MOBILE_TAG = "@mobile";

/**
 * `use` мобильного проекта: окно телефона 390×844 (iPhone 12/13/14), а не
 * сужение десктопного окна. `isMobile` включает мобильные ветки вёрстки
 * (`useMediaQuery("(min-width: 768px)")` в доске участка), `hasTouch` —
 * тач-события, `deviceScaleFactor: 2` — плотность экрана, при которой
 * проверяются «сжатые» размеры строк и кнопок.
 */
export const MOBILE_USE = {
  viewport: { width: 390, height: 844 },
  isMobile: true,
  hasTouch: true,
  deviceScaleFactor: 2,
};

/**
 * Ярусный тег как токен, а не как подстрока (#342, ревью 5).
 *
 * Один шаблон на все три места, где тег решает судьбу спеки: `grep` проекта,
 * `grepInvert` соседних проектов (`playwright.config.ts`) и список спеков в
 * отчёте прогона (`selectMobileSpecs`). Прежняя расстановка оставляла в конфиге
 * подстрочные `/@mobile/`, `/@ui/`, `/@ui-narrow/`: тег `@mobile-smoke` утащил
 * бы спеку в мобильный прогон, но в его же отчёте она бы не появилась, а спека
 * с `@ui-narrow @mobile` отработала бы в двух ярусах за один полный прогон
 * (у `ui-narrow` инверта не было вовсе). Границы `(^|[^\w-])` и `(?![\w-])`
 * отсекают и чужое начало (`X@mobile`), и чужое продолжение (`@mobile-smoke`).
 *
 * Флага `g` нет сознательно: `RegExp` с `g` помнит `lastIndex`, и один и тот же
 * объект, применённый к нескольким заголовкам подряд, врал бы на втором.
 */
export function tagRe(...tags) {
  const body = tags
    .map((tag) => tag.replace(/[.*+?^${}()|[\]\\]/g, "\\$&"))
    .join("|");
  return new RegExp(`(^|[^\\w-])(?:${body})(?![\\w-])`);
}

/**
 * Шаблон мобильного яруса: тот же объект уходит в `grep` проекта `mobile` и в
 * `grepInvert` десктопных проектов (`playwright.config.ts`), поэтому отбор спеки
 * в ярус и её список в отчёте не могут разойтись.
 */
export const MOBILE_TAG_RE = tagRe(MOBILE_TAG);

/**
 * Спеки мобильного яруса из содержимого каталога `e2e/`.
 *
 * На вход — пары `{ file, content }`, а не путь: чтение файлов живёт в
 * `run-tier.mjs`, здесь только решение «эта спека мобильная или нет», и его
 * можно проверить без диска.
 */
export function selectMobileSpecs(entries) {
  return entries
    .filter((entry) => MOBILE_TAG_RE.test(entry.content))
    .map((entry) => entry.file)
    .sort();
}

/** Строки отчёта мобильного прогона: окно, touch и список спеков. */
export function formatMobileReport(specFiles) {
  const { viewport, isMobile, hasTouch, deviceScaleFactor } = MOBILE_USE;
  const lines = [
    `[e2e:run] ярус ${MOBILE_PROJECT}: окно ${viewport.width}×${viewport.height}, ` +
      `isMobile=${isMobile}, hasTouch=${hasTouch}, deviceScaleFactor=${deviceScaleFactor}`,
  ];
  if (specFiles.length === 0) {
    // Пустой набор — не «всё хорошо»: прогон отработает вхолостую и покажет
    // зелёный код. Отчёт обязан сказать это прямо.
    lines.push(
      `[e2e:run] ярус ${MOBILE_PROJECT}: спек с тегом ${MOBILE_TAG} нет — прогон пройдёт вхолостую`,
    );
  } else {
    lines.push(
      `[e2e:run] ярус ${MOBILE_PROJECT}: ${MOBILE_TAG}-спек ${specFiles.length}: ` +
        specFiles.join(", "),
    );
  }
  return lines;
}
