/**
 * Сериализованный запуск одного яруса E2E.
 *
 * Зачем
 * -----
 * E2E ходят в ОДНО живое dev-окружение: один Postgres, один backend на :8012,
 * один фронт на :5172. А ещё `apiResetAll()` в `beforeEach` чистит базу целиком.
 * Два параллельных прогона поэтому несовместимы: второй `globalSetup` убьёт
 * стек первого (`ensure-dev-ports.js --kill`), а данные одного теста сотрут
 * данные другого.
 *
 * Когда несколько агентов правят разные ярусы, каждый прогон должен брать
 * этот скрипт, а не звать `playwright test` напрямую. Скрипт держит
 * эксклюзивный лок-файл: ждущий агент блокируется, пока стек свободен.
 *
 * Использование
 * -------------
 *   node e2e/run-tier.mjs smoke
 *   node e2e/run-tier.mjs ui-e2e
 *   node e2e/run-tier.mjs ui-narrow
 *
 * Опции (через env):
 *   E2E_LOCK_TIMEOUT_MS  сколько ждать чужой прогон (по умолчанию 30 мин)
 *   E2E_LOCK_STALE_MS    после какого возраста лок считается брошенным и
 *                        подбирается (по умолчанию 40 мин)
 *
 * Лок-файл: `node_modules/.e2e-run.lock` (в `.gitignore` через node_modules).
 */

import { spawnSync } from "node:child_process";
import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";

const E2E_DIR = path.dirname(fileURLToPath(import.meta.url));
const FRONTEND_DIR = path.resolve(E2E_DIR, "..");
const LOCK_DIR = path.join(FRONTEND_DIR, "node_modules", ".e2e-run");
const LOCK_FILE = path.join(LOCK_DIR, "current.lock");

const WAIT_TIMEOUT_MS = Number(process.env.E2E_LOCK_TIMEOUT_MS ?? 30 * 60_000);
const STALE_MS = Number(process.env.E2E_LOCK_STALE_MS ?? 40 * 60_000);
const POLL_MS = 3_000;

const TIER = process.argv[2];
const VALID_TIERS = ["smoke", "ui-e2e", "ui-narrow"];
if (!VALID_TIERS.includes(TIER)) {
  console.error(`Usage: node e2e/run-tier.mjs <${VALID_TIERS.join("|")}>`);
  process.exit(2);
}

const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

/** Пишет лок эксклюзивно; false — лок уже держит кто-то другой. */
function tryAcquire(payload) {
  fs.mkdirSync(LOCK_DIR, { recursive: true });
  try {
    // "wx" — атомарно: файл создаётся, только если его не было.
    fs.writeFileSync(LOCK_FILE, JSON.stringify(payload), { flag: "wx" });
    return true;
  } catch (err) {
    if (err.code === "EEXIST") return false;
    throw err;
  }
}

function readLock() {
  try {
    return JSON.parse(fs.readFileSync(LOCK_FILE, "utf8"));
  } catch {
    return null;
  }
}

/** Ждёт свободный лок, показывая, кто держит прошлый. */
async function acquire() {
  const started = Date.now();
  let announced = false;
  for (;;) {
    const holder = readLock();
    const age = holder ? Date.now() - (holder.at ?? Date.now()) : Infinity;
    if (holder && age > STALE_MS) {
      console.log(`[e2e:run] лок брошен (${Math.round(age / 60_000)} мин), подбираю себе`);
      fs.rmSync(LOCK_FILE, { force: true });
      continue;
    }
    if (tryAcquire({ tier: TIER, pid: process.pid, at: Date.now() })) return;
    if (!announced) {
      console.log(
        `[e2e:run] ярус ${TIER} ждёт: стек занят прогоном яруса ${holder?.tier ?? "?"} ` +
          `(pid ${holder?.pid ?? "?"}, ${Math.round(age / 60_000)} мин назад)`,
      );
      announced = true;
    }
    if (Date.now() - started > WAIT_TIMEOUT_MS) {
      throw new Error(
        `[e2e:run] не дождался свободного стека за ${Math.round(WAIT_TIMEOUT_MS / 60_000)} мин. ` +
          `Держит: ${JSON.stringify(holder)}`,
      );
    }
    await sleep(POLL_MS);
  }
}

function release() {
  fs.rmSync(LOCK_FILE, { force: true });
}

function onExit() {
  release();
}
process.on("exit", onExit);
for (const sig of ["SIGINT", "SIGTERM"]) {
  process.on(sig, () => {
    release();
    process.exit(130);
  });
}

await acquire();
const startedAt = Date.now();
console.log(`[e2e:run] === ярус ${TIER}: стек мой, запускаю прогон ===`);

// БД готовим ПОД локом: `e2e:prep` поднимает Docker, ждёт его и накатывает
// миграции. Без этого прогоны падают на «БД недоступна»: стеком владеет
// Playwright (`webServer`) и Docker он больше не поднимает сам.
// Под локом — обязательно: два параллельных `e2e:prep` бьются за один Docker.
const prep = spawnSync("npm", ["run", "e2e:prep"], {
  cwd: FRONTEND_DIR,
  encoding: "utf8",
  shell: true,
  maxBuffer: 32 * 1024 * 1024,
});
if (prep.status !== 0) {
  console.log(`[e2e:run] e2e:prep не прошёл (код ${prep.status}):`);
  console.log(`${prep.stdout ?? ""}${prep.stderr ?? ""}`.slice(-3000));
  release();
  process.exit(prep.status ?? 1);
}
console.log(`[e2e:run] e2e:prep ok (БД поднята, миграции накаты)`);

const result = spawnSync(
  "npx",
  ["playwright", "test", "--project", TIER, "--no-deps", "--reporter=list"],
  {
    cwd: FRONTEND_DIR,
    encoding: "utf8",
    shell: true,
    maxBuffer: 64 * 1024 * 1024,
  },
);

const wall = Math.round((Date.now() - startedAt) / 1000);
const output = `${result.stdout ?? ""}${result.stderr ?? ""}`;
release();

console.log(output);
console.log(`[e2e:run] === ярус ${TIER}: ${wall}s, код ${result.status} ===`);

// Код прогона наружу, чтобы вызывающая оболочка/агент увидел вердикт.
process.exit(result.status ?? 1);
