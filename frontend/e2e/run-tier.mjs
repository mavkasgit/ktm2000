/**
 * Сериализованный запуск одного яруса E2E — единственная точка входа прогона.
 *
 * Зачем
 * -----
 * Стенд у каждого прогона свой (порты выдаёт ОС, см. `scripts/run-e2e.mjs`),
 * но **БД общая**: `ktm2000_e2e` на :5441, и `apiResetAll()` в `beforeEach`
 * чистит её целиком. Два параллельных прогона поэтому несовместимы: данные
 * одного теста сотрут данные другого, и вердикт обоих станет нечитаемым.
 *
 * Скрипт держит эксклюзивный лок-файл: ждущий прогон блокируется, пока
 * предыщий не освободит лок. Порты не сериализуются — они и не конфликтуют.
 *
 * Именно этот скрипт, а не `playwright test` напрямую: владельцем стенда
 * (порты, `E2E_API_URL`, `PLAYWRIGHT_TEST_BASE_URL`, `CORS_ORIGINS`) остаётся
 * `scripts/run-e2e.mjs`, и звать Playwright мимо него нельзя — конфиг
 * требует эти переменные и падает без них.
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
 * Аргументы после яруса уходят в `playwright test` как есть: `npm run
 * e2e:run -- ui-e2e --ui` (режим UI, см. `test:e2e:ui-mode`), `--debug`,
 * `--headed`, `-g`, путь к спеке. Наш дефолт `--reporter=list` в UI-режиме
 * не добавляется — там репортер задаёт сам Playwright.
 *
 * Лок-файл: `node_modules/.e2e-run/current.lock` (в `.gitignore` через
 * node_modules). Прежняя шапка называла `node_modules/.e2e-run.lock` — этого
 * пути в коде нет.
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
// `all` — полный прогон: Playwright сам проходит проекты по `dependencies`
// (smoke → ui-e2e → ui-narrow) одним вызовом, стенд поднимается один раз.
const VALID_TIERS = ["all", "smoke", "ui-e2e", "ui-narrow"];
if (!VALID_TIERS.includes(TIER)) {
  console.error(`Usage: node e2e/run-tier.mjs <${VALID_TIERS.join("|")}>`);
  process.exit(2);
}
const projectArgs = TIER === "all" ? [] : ["--project", TIER];
// Аргументы после яруса уходят в `playwright test` как есть: отладка
// (`--debug`, `--headed`, `-g`, путь к спеке) и режим UI (`--ui`) приходят
// именно так — `npm run test:e2e:ui-mode`. Они идут ПОСЛЕ наших дефолтов,
// чтобы пользовательский флаг перебил дефолтный, а не наоборот.
const extraArgs = process.argv.slice(3);

// Режим UI Playwright (`--ui`, `--ui-host`, `--ui-port`) — интерактивный: он
// сам поднимает окно и живёт, пока его не закрыли. Два следствия:
//
//  * репортер нашёлкивать нельзя: `--reporter=list` уехал бы в панель отчётов
//    UI-режима, и она осталась бы пустой. Там нужен репортер самого Playwright;
//  * вывод должен идти в терминал сразу (`stdio: "inherit"`), а не копиться
//    в буфере `spawnSync` до закрытия окна — иначе отладка, ради которой
//    режим существует, ничего не показывает, пока не поздно.
const uiMode = extraArgs.some(
  (arg) => arg === "--ui" || arg === "--ui-host" || arg === "--ui-port",
);

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

// Playwright запускается ЧЕРЕЗ `scripts/run-e2e.mjs`, а не напрямую: обёртка
// выдаёт стенду свободные порты и прописывает `E2E_API_URL` /
// `PLAYWRIGHT_TEST_BASE_URL`, без которых конфиг падает на чтении. Обёртка
// пробрасывает stdio и код выхода, поэтому вердикт не теряется.
//
// `--no-deps` — только для одиночного яруса: у него `dependencies` нет, и флаг
// защищает от лишней фазы. На `all` он бы оборвал цепочку smoke → ui-e2e →
// ui-narrow, то есть тир `@ui` пошёл бы без своего предусловия.
const result = spawnSync(
  process.execPath,
  [
    path.join(FRONTEND_DIR, "scripts", "run-e2e.mjs"),
    ...projectArgs,
    ...(TIER === "all" ? [] : ["--no-deps"]),
    ...(uiMode ? [] : ["--reporter=list"]),
    ...extraArgs,
  ],
  uiMode
    ? { cwd: FRONTEND_DIR, shell: false, stdio: "inherit" }
    : {
        cwd: FRONTEND_DIR,
        encoding: "utf8",
        shell: false,
        maxBuffer: 64 * 1024 * 1024,
      },
);

// В UI-режиме вывод уже ушёл в терминал как есть (`stdio: "inherit"`), а
// `result.stdout` пуст — печатать его повторно нечего.
const wall = Math.round((Date.now() - startedAt) / 1000);
if (!uiMode) {
  console.log(`${result.stdout ?? ""}${result.stderr ?? ""}`);
}
release();
console.log(`[e2e:run] === ярус ${TIER}: ${wall}s, код ${result.status} ===`);

// Код прогона наружу, чтобы вызывающая оболочка/агент увидел вердикт.
process.exit(result.status ?? 1);
