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
 * атомарно (`wx`), освобождается в `finally`; чужой слот подбирается, если
 * процесс-держатель умер или слот висит дольше `staleMs`.
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

/** Занять свободный слот или вернуть null, если все заняты. */
export function tryAcquireSlot(dir, max, payload, { alive = isProcessAlive } = {}) {
  fs.mkdirSync(dir, { recursive: true });
  for (let index = 0; index < max; index += 1) {
    const file = slotFile(dir, index);
    const holder = readHolder(file);
    if (holder && !alive(holder.pid)) {
      // Держатель умер, не достучавшись до `finally` (kill -9, падение ОС).
      fs.rmSync(file, { force: true });
    }
    try {
      fs.writeFileSync(file, JSON.stringify(payload), { flag: "wx" });
      return { index, file };
    } catch (err) {
      if (err.code !== "EEXIST") throw err;
    }
  }
  return null;
}

export function releaseSlot(slot) {
  if (slot?.file) fs.rmSync(slot.file, { force: true });
}

/** Кто держит слоты — для строки ожидания. */
export function describeHolders(dir, max, { alive = isProcessAlive } = {}) {
  const holders = [];
  for (let index = 0; index < max; index += 1) {
    const holder = readHolder(slotFile(dir, index));
    if (holder) holders.push({ index, holder, alive: alive(holder.pid) });
  }
  return holders;
}

/**
 * Ждать свободный слот, показывая, что занято.
 *
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
  alive = isProcessAlive,
  now = Date.now,
} = {}) {
  const started = now();
  let announced = false;
  for (;;) {
    for (let index = 0; index < max; index += 1) {
      const file = slotFile(dir, index);
      const holder = readHolder(file);
      const age = holder ? now() - (holder.at ?? 0) : 0;
      if (holder && (age > staleMs || !alive(holder.pid))) {
        log(
          `[e2e:run] слот ${index}: держатель (pid ${holder.pid ?? "?"}, ` +
            `${Math.round(age / 60_000)} мин) мёртв или просрочен — снимаю`,
        );
        fs.rmSync(file, { force: true });
      }
    }
    const slot = tryAcquireSlot(dir, max, payload, { alive });
    if (slot) return slot;
    if (!announced) {
      const busy = describeHolders(dir, max, { alive })
        .map(({ index, holder }) => `слот ${index}: ${holder.repo ?? "?"} (pid ${holder.pid ?? "?"})`)
        .join(", ");
      log(`[e2e:run] жду слот: занято ${max}/${max} — ${busy}`);
      announced = true;
    }
    if (now() - started > waitTimeoutMs) {
      throw new Error(
        `[e2e:run] не дождался слота семафора за ${formatDuration(waitTimeoutMs)} ` +
          `(E2E_MAX_PARALLEL_RUNS=${max}); держат: ${JSON.stringify(describeHolders(dir, max, { alive }))}`,
      );
    }
    await new Promise((resolve) => setTimeout(resolve, pollMs));
  }
}
