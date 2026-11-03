/**
 * Слоты E2E — тонкий адаптер над общим машинным семафором (#281).
 *
 * Механика слота (файл `slot-N.json`, атомарный захват `wx`, снятие мёртвого
 * держателя, сверка pid при освобождении, отчёт «кто держит») живёт в
 * [`scripts/heavy-core.mjs`](../../scripts/heavy-core.mjs) — тот же семафор
 * считает pytest, tsc, eslint и сборки. Здесь остаётся только то, что
 * специфично для E2E:
 *
 *  * свой каталог слотов (`%LOCALAPPDATA%\ktm2000-e2e\slots`), потому что
 *    стенд — отдельный ресурс: он держит браузеры, Postgres-клон и порты;
 *  * своё число слотов (`E2E_MAX_PARALLEL_RUNS`, по умолчанию 2) и свой
 *    таймаут ожидания (`E2E_SEMAPHORE_TIMEOUT_MS`, 30 мин);
 *  * свой порог подозрения (`DEFAULT_STALE_MS`, 40 мин): живой держатель слот
 *    не уступает ни при каком возрасте (#375);
 *  * префикс `[e2e:run]` в строках ожидания — по нему читают лог прогона.
 *
 * Каталог слотов вне репозитория: `%LOCALAPPDATA%\ktm2000-e2e\slots` (Windows)
 * или `$XDG_STATE_HOME/ktm2000-e2e/slots` (иначе). Переопределяется
 * `E2E_SEMAPHORE_DIR`.
 */

import path from "node:path";

import {
  acquireSlot as poolAcquireSlot,
  defaultStateBase,
  isProcessAlive,
  resolvePositiveInt,
} from "../../scripts/heavy-core.mjs";

export const DEFAULT_MAX_RUNS = 2;
export const DEFAULT_WAIT_TIMEOUT_MS = 30 * 60_000;
/**
 * С какого возраста ЖИВОГО держателя считать его подозреваемым в зависании.
 * Слот по этому порогу не освобождается (#375) — только называется в логе.
 */
export const DEFAULT_STALE_MS = 40 * 60_000;

/** Прогон идёт минуты: опрос раз в 3 с не жжёт CPU и не задерживает старт. */
const POLL_MS = 3_000;

/** Каталог слотов вне репозитория: свой у машины, общий для всех worktree. */
export function defaultSlotsDir(env = process.env, platform = process.platform) {
  return path.join(defaultStateBase(env, platform), "ktm2000-e2e", "slots");
}

/** Число одновременных прогонов: `E2E_MAX_PARALLEL_RUNS`, но не меньше одного. */
export function resolveMaxRuns(env = process.env) {
  return resolvePositiveInt(
    env.E2E_MAX_PARALLEL_RUNS ?? DEFAULT_MAX_RUNS,
    "E2E_MAX_PARALLEL_RUNS",
  );
}

/**
 * Ждать свободный слот прогона, показывая, что занято.
 *
 * @param {object} [options]
 * @param {string} [options.dir] каталог слотов (вне репозитория — видит вся машина)
 * @param {number} [options.max] число слотов (`E2E_MAX_PARALLEL_RUNS`)
 * @param {Record<string, unknown>} [options.payload] содержимое файла слота: `repo`,
 *   `runId`, `envFile`, `tier`, `pid`, `at`
 * @param {number} [options.waitTimeoutMs] сколько ждать свободный слот
 * @param {number} [options.staleMs] возраст, с которого живой держатель называется
 *   в логе как подозреваемый в зависании; слот по нему НЕ освобождается (#375)
 * @param {number} [options.pollMs] шаг опроса
 * @param {(line: string) => void} [options.log]
 * @param {(holder: Record<string, unknown>, info: {index: number, reason: string}) => void} [options.onReclaim]
 * @param {(pid: number) => boolean} [options.alive] чем проверять живость держателя
 * @param {() => number} [options.now] часы (для тестов)
 * @returns {Promise<{index: number, file: string, pid?: number}>}
 */
export async function acquireSlot({
  dir = defaultSlotsDir(),
  max = resolveMaxRuns(),
  payload,
  waitTimeoutMs = DEFAULT_WAIT_TIMEOUT_MS,
  staleMs = DEFAULT_STALE_MS,
  pollMs = POLL_MS,
  log = console.log,
  onReclaim,
  alive = isProcessAlive,
  now = Date.now,
} = {}) {
  return poolAcquireSlot({
    dir,
    max,
    payload,
    waitTimeoutMs,
    staleMs,
    pollMs,
    log: (line) => log(`[e2e:run] ${line}`),
    onReclaim,
    alive,
    now,
  });
}
