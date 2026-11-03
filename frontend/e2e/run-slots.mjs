/**
 * Счётный семафор на одновременные прогоны E2E на машине (#281).
 *
 * Зачем
 * -----
 * Лок `node_modules/.e2e-run/current.lock` в `run-tier.mjs` сериализует прогоны
 * только внутри одного репозитория/worktree: `node_modules` у каждого дерева
 * свой, и два прогона из разных worktree этот лок не видят вовсе. Своя БД на
 * репозиторий (#269) сняла гонку за данные, но не ограничила число стендов на
 * машине: два параллельных прогона делят CPU, память и браузеры, и вердикт
 * обоих становится нечитаемым (таймауты вместо падений продукта).
 *
 * Здесь — машинный (не репозиторный) счётчик: каталог слотов живёт вне
 * репозитория, поэтому виден всем worktree. Свободный слот занимается
 * атомарно (`wx`), освобождается в `finally`; чужой слот подбирается, только
 * если процесс-держатель умер. Возраст сам по себе слот не освобождает (#375):
 * просроченный, но ЖИВОЙ держатель — это долгий прогон, а отняв слот у него,
 * сосед начинает второй стенд на той же машине, и перестают читаться вердикты
 * обоих. Такой держатель виден в логе ожидания как предупреждение.
 *
 * Каталог слотов: `%LOCALAPPDATA%\ktm2000-e2e\slots` (Windows) или
 * `$XDG_STATE_HOME/ktm2000-e2e/slots` (иначе). Переопределяется
 * `E2E_SEMAPHORE_DIR` — тесты и ручные прогоны.
 *
 * Число слотов: `E2E_MAX_PARALLEL_RUNS` (по умолчанию 2). Машина 8 ядер /
 * 16 потоков тянет два стенда; на меньшей — ставьте 1, это ровно прежнее
 * поведение «один прогон на машину».
 */

import fs from "node:fs";
import os from "node:os";
import path from "node:path";

export const DEFAULT_MAX_RUNS = 2;
export const DEFAULT_WAIT_TIMEOUT_MS = 30 * 60_000;
/**
 * С какого возраста ЖИВОГО держателя считать его подозреваемым в зависании.
 * Слот по этому порогу не освобождается (#375) — только называется в логе.
 */
export const DEFAULT_STALE_MS = 40 * 60_000;

const POLL_MS = 3_000;

/** Длительность для сообщений: секунды до минуты, дальше — минуты. */
function formatDuration(ms) {
  return ms < 60_000 ? `${Math.round(ms / 1000)} с` : `${Math.round(ms / 60_000)} мин`;
}

/** Каталог слотов вне репозитория: свой у машины, общий для всех worktree. */
export function defaultSlotsDir() {
  const base =
    process.platform === "win32"
      ? process.env.LOCALAPPDATA ?? path.join(os.homedir(), "AppData", "Local")
      : process.env.XDG_STATE_HOME ?? path.join(os.homedir(), ".local", "state");
  return path.join(base, "ktm2000-e2e", "slots");
}

/** Число одновременных прогонов: `E2E_MAX_PARALLEL_RUNS`, но не меньше одного. */
export function resolveMaxRuns(env = process.env) {
  const raw = Number(env.E2E_MAX_PARALLEL_RUNS ?? DEFAULT_MAX_RUNS);
  if (!Number.isInteger(raw) || raw < 1) {
    throw new Error(
      `E2E_MAX_PARALLEL_RUNS=${env.E2E_MAX_PARALLEL_RUNS} — нужно целое ≥ 1`,
    );
  }
  return raw;
}

export function slotFile(dir, index) {
  return path.join(dir, `slot-${index}.json`);
}

/** Живой ли процесс. Неизвестная ошибка → «жив»: слот не отнимаем. */
export function isProcessAlive(pid) {
  if (!Number.isInteger(pid) || pid <= 0) return false;
  try {
    process.kill(pid, 0);
    return true;
  } catch (err) {
    return err.code !== "ESRCH";
  }
}

function readHolder(file) {
  try {
    return JSON.parse(fs.readFileSync(file, "utf8"));
  } catch {
    return null;
  }
}

/**
 * Занять свободный слот или вернуть null, если все заняты.
 *
 * `onReclaim(holder)` зовётся для каждого слота, чей держатель **мёртв**,
 * непосредственно перед удалением файла слота. Это единственный момент, когда
 * известно, чей прогон оставил клоны: файл слота удаляется, и следующий читатель
 * уже ничего не увидит (#306, уборка клонов брошенного прогона в чужом
 * дереве). Возраст слота для этого НЕ годится: вызывающий получит только
 * умершие держатели.
 */
export function tryAcquireSlot(dir, max, payload, { alive = isProcessAlive, onReclaim } = {}) {
  fs.mkdirSync(dir, { recursive: true });
  for (let index = 0; index < max; index += 1) {
    const file = slotFile(dir, index);
    const holder = readHolder(file);
    if (holder && !alive(holder.pid)) {
      // Держатель умер, не достучавшись до `finally` (kill -9, падение ОС).
      onReclaim?.(holder, { index, reason: "держатель мёртв" });
      fs.rmSync(file, { force: true });
    }
    try {
      fs.writeFileSync(file, JSON.stringify(payload), { flag: "wx" });
      // `pid` в слоте — для `releaseSlot`: он сверяет, что отпускает свой
      // слот, а не тот, который уже отобран соседу.
      return { index, file, pid: payload?.pid };
    } catch (err) {
      if (err.code !== "EEXIST") throw err;
    }
  }
  return null;
}

/**
 * Отпускает слот **только если он всё ещё наш**.
 *
 * Файл слота бывает чужим к моменту `finally`: мёртвого держателя снимают, и
 * сосед занимает тот же индекс. Прежний прогон зовёт `releaseSlot` для файла,
 * который ему уже не принадлежит, — слот исчез бы из-под работающего соседа, и
 * семафор перестал бы считать (доказано в `docs/night/tickets/R-04.md`).
 * Поэтому сверяем pid держателя.
 */
export function releaseSlot(slot) {
  if (!slot?.file) return;
  const holder = readHolder(slot.file);
  if (holder && holder.pid !== slot.pid) return;
  fs.rmSync(slot.file, { force: true });
}

/** Кто держит слоты — для строки ожидания. `ageMs` — сколько висит этот слот. */
export function describeHolders(dir, max, { alive = isProcessAlive, now = Date.now } = {}) {
  const holders = [];
  for (let index = 0; index < max; index += 1) {
    const holder = readHolder(slotFile(dir, index));
    if (holder) {
      holders.push({
        index,
        holder,
        alive: alive(holder.pid),
        ageMs: now() - (holder.at ?? now()),
      });
    }
  }
  return holders;
}

/**
 * @typedef {Object} AcquireSlotOptions
 * @property {string} [dir] каталог слотов (вне репозитория — видит вся машина)
 * @property {number} [max] число слотов (`E2E_MAX_PARALLEL_RUNS`)
 * @property {Record<string, *>} [payload] содержимое файла слота: `repo`, `runId`,
 *   `envFile`, `tier`, `pid`, `at`. Без описания в JSDoc тип выводится из
 *   значения по умолчанию `{}` и `payload` в него не попадает — вызывающий
 *   (`run-slots.test.ts`) падает на TS2353, хотя аргумент обязательный по смыслу.
 * @property {number} [waitTimeoutMs] сколько ждать свободный слот
 * @property {number} [staleMs] возраст, с которого живой держатель называется в
 *   логе как подозреваемый в зависании; слот по нему НЕ освобождается (#375)
 * @property {number} [pollMs] шаг опроса
 * @property {(line: string) => void} [log]
 * @property {(holder: Record<string, *>, info: {index: number, reason: string}) => void} [onReclaim]
 * @property {(pid: number) => boolean} [alive] чем проверять живость держателя
 * @property {() => number} [now] часы (для тестов)
 */

/**
 * Ждать свободный слот, показывая, что занято.
 *
 * @param {AcquireSlotOptions} [options]
 * @returns {Promise<{index: number, file: string}>}
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
  const started = now();
  let announced = false;
  let warned = false;
  for (;;) {
    for (let index = 0; index < max; index += 1) {
      const file = slotFile(dir, index);
      const holder = readHolder(file);
      if (!holder) continue;
      if (!alive(holder.pid)) {
        log(
          `[e2e:run] слот ${index}: держатель (pid ${holder.pid ?? "?"}) мёртв — снимаю`,
        );
        // Мёртвый держатель — единственный повод отдать его слот вызывающему:
        // его прогон не убрал за собой клоны (#306).
        onReclaim?.(holder, { index, reason: "держатель мёртв" });
        fs.rmSync(file, { force: true });
        continue;
      }
      const age = now() - (holder.at ?? now());
      if (age > staleMs && !warned) {
        // Держатель жив: слот НЕ отнимаем. Возраст — не право отбора, а вопрос
        // человеку: долгий прогон и зависший выглядят одинаково, пока не назван
        // возраст.
        warned = true;
        log(
          `[e2e:run] слот ${index}: держатель жив (pid ${holder.pid ?? "?"}, ` +
            `${Math.round(age / 60_000)} мин, репозиторий ${holder.repo ?? "?"}) — ` +
            `слот не отнимаю; порог подозрения ${Math.round(staleMs / 60_000)} мин`,
        );
      }
    }
    const slot = tryAcquireSlot(dir, max, payload, { alive, onReclaim });
    if (slot) return slot;
    if (!announced) {
      const busy = describeHolders(dir, max, { alive, now })
        .map(
          ({ index, holder, ageMs }) =>
            `слот ${index}: ${holder.repo ?? "?"} (pid ${holder.pid ?? "?"}, ${formatDuration(ageMs)})`,
        )
        .join(", ");
      log(`[e2e:run] жду слот: занято ${max}/${max} — ${busy}`);
      announced = true;
    }
    if (now() - started > waitTimeoutMs) {
      const held = describeHolders(dir, max, { alive, now })
        .map(
          ({ index, holder, ageMs, alive: isAlive }) =>
            `слот ${index}: ${holder.repo ?? "?"} (pid ${holder.pid ?? "?"}, ` +
            `${isAlive ? "жив" : "мёртв"}, ${formatDuration(ageMs)})`,
        )
        .join("; ");
      throw new Error(
        `[e2e:run] не дождался слота семафора за ${formatDuration(waitTimeoutMs)} ` +
          `(E2E_MAX_PARALLEL_RUNS=${max}); держат: ${held}. ` +
          "Живой держатель слота не уступает по возрасту — если прогон завис, решать надо по pid",
      );
    }
    await new Promise((resolve) => setTimeout(resolve, pollMs));
  }
}
