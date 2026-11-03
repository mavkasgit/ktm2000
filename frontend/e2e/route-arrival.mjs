/**
 * Переход на маршрут в E2E: «доехали» или «не доехали» — разные вещи (#289).
 *
 * Зачем модуль
 * ------------
 * Серия прогонов `--workers=2` дала 1 падение из 10: после
 * `page.goto("/section-tasks")` заголовок «Участки» не появился за 10 с, а на
 * скриншоте остался прежний маршрут с открытым модальным окном и набранным
 * поиском — то есть состояние **прежнего документа** (новый документ модалки
 * предыдущего экрана не наследует). При этом `page.goto` не бросил: он вернул
 * управление, `waitUntil: "domcontentloaded"` его устроил.
 *
 * Отсюда правило: после перехода надо убедиться, что документ действительно
 * сменился, и только потом ждать монтирование маршрута. Ждать заголовок в
 * документе, который не переехал, бессмысленно — там нового маршрута не будет
 * никогда, и десять секунд ожидания выглядят как «медленный SPA», хотя это
 * другой отказ.
 *
 * Что делает `gotoRoute`
 * ----------------------
 * 1. Снимает `performance.timeOrigin` (идентичность документа), делает переход,
 *    снимает ещё раз.
 * 2. Документ тот же → ждать маршрут негде: переход повторяется (до
 *    `maxAttempts` раз). Это не ослабление проверки — заголовок по-прежнему
 *    обязателен, меняется только адресат ожидания.
 * 3. Документ новый → ждёт `waitForRoute(budgetMs)`. Первый заход получает
 *    `ARRIVAL_BUDGET_MS` (те же 10 с, что стояли у заголовка: на зелёных
 *    прогонах их хватало, менять бюджет «на всякий случай» значило бы
 *    замаскировать медленный первый рендер). Повторный заход — 
 *    `RENAVIGATE_BUDGET_MS`: документ холодный, ему нужны `/auth/me` с обходом
 *    кеша IdP, справочник ролей и чанк раздела.
 * 4. Бюджет кончился на последней попытке — функция **не бросает**: вердикт
 *    остаётся за ассертом вызывающего, чтобы падение читалось обычным текстом
 *    Playwright («заголовок не виден»), а не «gotoRoute: не доехали».
 *
 * Почему `.mjs`, а не `.ts`: файл импортирует и `ui-helpers.ts` (спеки), и
 * vitest-тест (`route-arrival.test.ts`) — как `run-workers.mjs`/`run-lock.mjs`.
 * Проверка поведения без стенда — там же, в тесте: у настоящего `page` нет
 * способа заставить `goto` молча ничего не сделать.
 */

/** Таймаут самой навигации: он же стоял у `page.goto` до #289. */
export const GOTO_TIMEOUT_MS = 60_000;

/** Бюджет первого ожидания маршрута после перехода — прежние 10 с у заголовка. */
export const ARRIVAL_BUDGET_MS = 10_000;

/** Бюджет повторного захода: документ холодный, кеша запросов у него нет. */
export const RENAVIGATE_BUDGET_MS = 15_000;

/** Переходов не больше двух: третий — это уже другой отказ, не флейк перехода. */
export const MAX_ARRIVAL_ATTEMPTS = 2;

/** Пауза перед повтором перехода после временного обрыва dev-сервера. */
const TRANSIENT_RETRY_PAUSE_MS = 1_000;

/**
 * Обрыв соединения с dev-сервером — временный: такой переход повторяем.
 * Таймаут и `ERR_ABORTED` сюда не входят: они означают не «сеть моргнула», а
 * «переход отменили/не уложились», и прятать их повтором нельзя.
 */
const TRANSIENT_NAVIGATION_ERROR =
  /ERR_CONNECTION_(?:TIMED_OUT|RESET|REFUSED)|ERR_NETWORK_CHANGED/;

const defaultSleep = (ms) => new Promise((resolve) => setTimeout(resolve, ms));

/** @param {string} message */
export function isTransientNavigationError(message) {
  return TRANSIENT_NAVIGATION_ERROR.test(message);
}

/**
 * Сменился ли документ между двумя снимками `performance.timeOrigin`.
 *
 * `null` — значение неизвестно (evaluate не отработал: контекст уже ушёл).
 * Неизвестность трактуется как «сменился»: тогда маршрут всё равно ждём, то
 * есть поведение остаётся строже, а не мягче.
 *
 * @param {number | null} before
 * @param {number | null} after
 */
export function documentWasReplaced(before, after) {
  if (before === null || after === null) return true;
  return before !== after;
}

/**
 * Идентичность текущего документа. `null` — прочитать не удалось (переход
 * оборвал контекст), а не «ноль».
 *
 * @param {{ evaluate: <T>(fn: () => T) => Promise<T> }} page
 * @returns {Promise<number | null>}
 */
async function documentOrigin(page) {
  try {
    const origin = await page.evaluate(() => performance.timeOrigin);
    return typeof origin === "number" && Number.isFinite(origin) ? origin : null;
  } catch {
    return null;
  }
}

/**
 * Один переход: `page.goto` с одной повторной попыткой только для временного
 * обрыва dev-сервера.
 *
 * @param {{ goto: (url: string, options: object) => Promise<unknown> }} page
 * @param {string} url
 * @param {{ timeoutMs: number, sleep: (ms: number) => Promise<void> }} options
 */
async function gotoWithTransientRetry(page, url, { timeoutMs, sleep }) {
  for (let attempt = 1; ; attempt++) {
    try {
      await page.goto(url, { waitUntil: "domcontentloaded", timeout: timeoutMs });
      return;
    } catch (error) {
      const message = error instanceof Error ? error.message : String(error);
      if (!isTransientNavigationError(message) || attempt >= 2) throw error;
      await sleep(TRANSIENT_RETRY_PAUSE_MS);
    }
  }
}

/**
 * Переход на маршрут с проверкой, что доехали до **нового** документа.
 *
 * @param {object} page — Playwright `Page` (нужны `goto` и `evaluate`).
 * @param {string} url
 * @param {object} options
 * @param {(budgetMs: number) => Promise<boolean>} options.waitForRoute —
 *   попытка дождаться монтирования маршрута в пределах бюджета; `false` —
 *   не дождались. Обязателен: без него «доехали» неотличимо от «не доехали».
 * @param {number} [options.timeoutMs]
 * @param {number} [options.arrivalBudgetMs]
 * @param {number} [options.renavigateBudgetMs]
 * @param {number} [options.maxAttempts]
 * @param {(ms: number) => Promise<void>} [options.sleep]
 * @param {(line: string) => void} [options.log]
 * @returns {Promise<void>}
 */
export async function gotoRoute(
  page,
  url,
  {
    waitForRoute,
    timeoutMs = GOTO_TIMEOUT_MS,
    arrivalBudgetMs = ARRIVAL_BUDGET_MS,
    renavigateBudgetMs = RENAVIGATE_BUDGET_MS,
    maxAttempts = MAX_ARRIVAL_ATTEMPTS,
    sleep = defaultSleep,
    log = () => {},
  } = {},
) {
  if (typeof waitForRoute !== "function") {
    throw new TypeError(
      "gotoRoute: нужен waitForRoute — иначе «доехали» неотличимо от «не доехали»",
    );
  }

  for (let attempt = 1; attempt <= maxAttempts; attempt++) {
    const before = await documentOrigin(page);
    await gotoWithTransientRetry(page, url, { timeoutMs, sleep });
    const after = await documentOrigin(page);

    if (!documentWasReplaced(before, after)) {
      log(
        `[goto] ${url}: документ не сменился (попытка ${attempt}/${maxAttempts}) — ` +
          "повторяю переход, ждать маршрут в прежнем документе нечего",
      );
      continue;
    }

    const budgetMs = attempt === 1 ? arrivalBudgetMs : renavigateBudgetMs;
    if (await waitForRoute(budgetMs)) {
      if (attempt > 1) log(`[goto] ${url}: маршрут смонтировался с попытки ${attempt}`);
      return;
    }

    log(
      `[goto] ${url}: маршрут не смонтировался за ${budgetMs} мс ` +
        `(попытка ${attempt}/${maxAttempts}) — ` +
        (attempt < maxAttempts ? "перезагружаю" : "вердикт отдаю ассерту"),
    );
  }
}
