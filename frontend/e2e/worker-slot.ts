/**
 * Слот стенда, к которому принадлежит воркер Playwright (#289).
 *
 * Что за проблема
 * ---------------
 * `workerInfo.workerIndex` — **не** номер среди одновременно работающих
 * воркеров, а сквозной счётчик процессов: Playwright переиспользует слоты, но
 * номер выданного процесса растёт на всём прогоне. На прогоне `--workers=2` в
 * нескольких проектах доходят до `workerIndex` 2, 3 и 4 — при двух живых
 * backend'ах. Тот, кто взял индекс «как есть», уезжал в никуда: `urls[4]` при
 * двух адресах — `undefined`.
 *
 * Поэтому слот считается **не** от `workerIndex`. Кандидат «`workerIndex` по
 * модулю числа воркеров» тоже неверен, и это не теория: на полном прогоне
 * `--workers=2` живая пара процессов дала `workerIndex` `{0, 2}` → оба
 * `slot 0` → два воркера сеяли **одну** БД и падали на
 * `UniqueViolation uq_product_dimensions_product_type`. Модуль не гарантирует
 * уникальность среди живых: индексы 0 и 2 не пересекаются во времени, но
 * остаток у них один.
 *
 * Что даёт уникальность
 * ---------------------
 * `workerInfo.parallelIndex` — по документации Playwright «индекс воркера
 * между 0 и `workers - 1`; гарантируется, что одновременно работающие воркеры
 * имеют разные `parallelIndex`. При перезапуске воркера новый процесс получает
 * тот же `parallelIndex`» (docs/test-parallel, `workerInfo.parallelIndex`).
 * Это ровно нужный контракт: слот занят, пока его процесс жив.
 *
 * В воркерном процессе то же значение лежит в `process.env.TEST_PARALLEL_INDEX`
 * — `worker-slot.ts` читает переменную, а не `workerInfo`: модуль грузится
 * внутри воркера, где Playwright её уже поставил, и она же нужна
 * `api-helpers` на этапе загрузки модуля (до создания фикстур).
 *
 * Проверка диапазона — не формальность. `parallelIndex` может выйти за
 * `E2E_WORKERS`, если Playwright запущен с бо́льшим `--workers`, чем выдано
 * клонов БД и backend'ов (`run-tier.mjs` держит их поровну). Молчаливое
 * «привести по модулю» вернуло бы ровно ту коллизию, ради устранения которой
 * всё это существует, поэтому такой случай — ошибка с текстом.
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
 * `parallelIndex` текущего воркера из окружения.
 *
 * Вне воркерного процесса (конфиг, юнит-тесты) переменной нет — это слот 0,
 * поведение одиночного прогона. А вот «воркерный процесс без
 * `TEST_PARALLEL_INDEX`» — невозможное состояние: Playwright ставит обе
 * переменные вместе, и молча уехать в слот 0 значило бы вернуть гонку сидов.
 */
export function readParallelIndex(env: NodeJS.ProcessEnv = process.env): number {
  const raw = env.TEST_PARALLEL_INDEX;
  if (raw === undefined || raw === "") {
    const workerIndex = env.TEST_WORKER_INDEX;
    if (workerIndex !== undefined && workerIndex !== "") {
      throw new Error(
        "Процесс воркерный " +
          `(TEST_WORKER_INDEX=${workerIndex}), но Playwright не поставил ` +
          "TEST_PARALLEL_INDEX: слот воркера считается по parallelIndex " +
          "(#289), а не по сквозному workerIndex — иначе два живых воркера " +
          "могут сеять одну БД. Обновите @playwright/test.",
      );
    }
    return 0;
  }
  const trimmed = raw.trim();
  if (!/^\d+$/.test(trimmed)) {
    throw new Error(`TEST_PARALLEL_INDEX должен быть неотрицательным целым, получено: ${raw}`);
  }
  return Number(trimmed);
}

let announced = false;

/** Одна строка на процесс воркера: по ней в логе видно, что слоты разошлись. */
function announceSlot(parallelIndex: number): void {
  if (announced) return;
  announced = true;
  if (process.env.TEST_PARALLEL_INDEX === undefined) return;
  console.log(
    `[e2e:worker] слот=${parallelIndex} parallelIndex=${parallelIndex} ` +
      `workerIndex=${process.env.TEST_WORKER_INDEX ?? "?"} pid=${process.pid}`,
  );
}

/**
 * Слот стенда для `parallelIndex`.
 *
 * Значение совпадает с `parallelIndex` (идентичность, а не остаток): Playwright
 * гарантирует уникальность среди живых воркеров, и именно это делает слот
 * адресом клона БД. `workers` — для проверки диапазона и для юнит-тестов.
 */
export function workerSlot(
  parallelIndex: number = readParallelIndex(),
  workers: number = E2E_WORKERS,
): number {
  if (!Number.isInteger(parallelIndex) || parallelIndex < 0) {
    throw new Error(`parallelIndex должен быть неотрицательным целым, получено: ${parallelIndex}`);
  }
  if (parallelIndex >= workers) {
    throw new Error(
      `parallelIndex=${parallelIndex}, а воркеров в прогоне ${workers}: ` +
        "клонов БД и backend'ов выдано меньше, чем процессов Playwright. " +
        "Такой прогон сеял бы одну БД из двух воркеров (#289). Запускайте " +
        "прогон через npm-скрипт: он держит `--workers`, клоны и backend'ы " +
        "поровну.",
    );
  }
  announceSlot(parallelIndex);
  return parallelIndex;
}

/** Адреса backend'ов по слотам; без `E2E_WORKER_API_URLS` — один адрес. */
export function workerBackendUrls(env: NodeJS.ProcessEnv = process.env): string[] {
  const raw = env.E2E_WORKER_API_URLS;
  return raw ? (JSON.parse(raw) as string[]) : [env.E2E_API_URL ?? ""];
}
