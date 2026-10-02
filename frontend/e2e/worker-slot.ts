/**
 * Слот стенда, к которому принадлежит воркер Playwright (#289).
 *
 * Что за проблема
 * ---------------
 * `workerInfo.workerIndex` — **не** номер среди одновременно работающих
 * воркеров, а сквозной счётчик процессов: Playwright переиспользует слоты, но
 * номер выданного процесса растёт на всём прогоне. На прогоне
 * `--workers=2` в трёх проектах доходят до `workerIndex` 2, 3 и 4 — при двух
 * живых backend'ах. Тот, кто взял индекс «как есть», уезжал в никуда:
 * `urls[4]` при двух адресах — `undefined`.
 *
 * Поэтому слот считается по модулю числа воркеров: `E2E_WORKERS` даёт
 * `run-tier.mjs` из `--workers`. Так как одновременно живых воркеров не больше
 * `E2E_WORKERS` (это и ограничивает сам Playwright), два работающих воркера
 * разных слотов не совпадут: слот занят, пока его процесс жив.
 *
 * Кто пользуется
 * --------------
 * `fixtures.ts` — заголовок `x-e2e-worker` для роутера `/api`;
 * `api-helpers.ts` — прямые вызовы из Node, которые идут мимо заголовка.
 * Оба берут слот отсюда, чтобы разойтись они не могли.
 */

/** Сколько воркеров (значит, сколько клонов БД и backend'ов) в прогоне. */
export const E2E_WORKERS = Math.max(1, Number(process.env.E2E_WORKERS ?? 1) || 1);

/**
 * Слот стенда для `workerIndex`.
 *
 * `TEST_WORKER_INDEX` читается, а не `workerInfo`: модуль грузится внутри
 * воркерного процесса, где Playwright эту переменную уже поставил, и она же
 * нужна `api-helpers` на этапе загрузки модуля (до создания фикстур).
 */
export function workerSlot(workerIndex: number = Number(process.env.TEST_WORKER_INDEX ?? 0)): number {
  return ((workerIndex % E2E_WORKERS) + E2E_WORKERS) % E2E_WORKERS;
}

/** Адреса backend'ов по слотам; без `E2E_WORKER_API_URLS` — один адрес. */
export function workerBackendUrls(): string[] {
  const raw = process.env.E2E_WORKER_API_URLS;
  return raw ? (JSON.parse(raw) as string[]) : [process.env.E2E_API_URL ?? ""];
}