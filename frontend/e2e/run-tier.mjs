/**
 * Сериализованный запуск одного яруса E2E — единственная точка входа прогона.
 *
 * Зачем
 * -----
 * Стенд у каждого прогона свой (порты выдаёт ОС, см. `scripts/run-e2e.mjs`),
 * а **БД — клон шаблона** (#281): `e2e:prep` собирает шаблонную БД с
 * миграциями и сидами один раз, а прогон получает свой `CREATE DATABASE …
 * TEMPLATE …`. Поэтому `apiResetAll()` в `beforeEach` чистит свою базу, и
 * параллельные прогоны больше не стирают данные друг друга.
 *
 * Владение прогоном осталось за этим скриптом, но разграничено так:
 *  * `node_modules/.e2e-run/current.lock` — **внутри репозитория**: отчёт
 *    Playwright, коллекция браузеров и `test-results` у дерева одни, второй
 *    прогон в том же worktree их бы перетёр;
 *  * счётный семафор `run-slots.mjs` — **на машине**: не больше
 *    `E2E_MAX_PARALLEL_RUNS` (по умолчанию 2) стендов одновременно, независимо
 *    от числа worktree. Каталог слотов вне репозитория, поэтому виден соседям.
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
 *   E2E_LOCK_TIMEOUT_MS     сколько ждать свободный лок репозитория (30 мин)
 *   E2E_LOCK_STALE_MS       после какого возраста лок считается брошенным (40 мин)
 *   E2E_MAX_PARALLEL_RUNS   сколько прогонов пускать на машине (2)
 *   E2E_SEMAPHORE_DIR       каталог слотов семафора (вне репозитория)
 *   E2E_SEMAPHORE_TIMEOUT_MS  сколько ждать слот (30 мин)
 *   E2E_RUN_ID              id клона БД; иначе случайный
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
import crypto from "node:crypto";
import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";

import {
  acquireSlot,
  defaultSlotsDir,
  releaseSlot,
  resolveMaxRuns,
} from "./run-slots.mjs";

const E2E_DIR = path.dirname(fileURLToPath(import.meta.url));
const FRONTEND_DIR = path.resolve(E2E_DIR, "..");
const REPO_ROOT = path.resolve(FRONTEND_DIR, "..");
const LOCK_DIR = path.join(FRONTEND_DIR, "node_modules", ".e2e-run");
const LOCK_FILE = path.join(LOCK_DIR, "current.lock");

const WAIT_TIMEOUT_MS = Number(process.env.E2E_LOCK_TIMEOUT_MS ?? 30 * 60_000);
const STALE_MS = Number(process.env.E2E_LOCK_STALE_MS ?? 40 * 60_000);
const POLL_MS = 3_000;
const SLOT_DIR = process.env.E2E_SEMAPHORE_DIR ?? defaultSlotsDir();
const MAX_RUNS = resolveMaxRuns();
const SLOT_TIMEOUT_MS = Number(process.env.E2E_SEMAPHORE_TIMEOUT_MS ?? 30 * 60_000);

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

// Прогон: id клона БД, его env-файл и занятый слот семафора. Уборка в
// `finalize()` идемпотентна — её зовут и штатный путь, и обработчики выхода.
const runId = (process.env.E2E_RUN_ID ?? crypto.randomBytes(4).toString("hex")).toLowerCase();
let runEnvFile = null;
let slot = null;
let finalized = false;

function finalize() {
  if (finalized) return;
  finalized = true;
  if (runEnvFile) {
    // Клон нужен ровно на время прогона: сносим его здесь же, пока держим
    // слот. Не вышло — клон уберёт `drop --stale-run-minutes` следующего prep.
    const drop = spawnSync("npm", ["run", "db:e2e:drop"], {
      // Скрипт `db:e2e:drop` объявлен в корневом package.json, а не во
      // frontend-овском: звать его надо из корня репозитория.
      cwd: REPO_ROOT,
      encoding: "utf8",
      shell: true,
      maxBuffer: 8 * 1024 * 1024,
      env: { ...process.env, E2E_RUN_ID: runId },
    });
    if ((drop.status ?? 1) !== 0) {
      console.log(
        `[e2e:run] клон ${runId}: уборка не прошла (код ${drop.status}) — ` +
          "снесётся следующим prep по возрасту:\n" +
          `${drop.stdout ?? ""}${drop.stderr ?? ""}`.slice(-800),
      );
    }
  }
  releaseSlot(slot);
  slot = null;
  release();
}

process.on("exit", finalize);
for (const sig of ["SIGINT", "SIGTERM"]) {
  process.on(sig, () => {
    finalize();
    process.exit(130);
  });
}

await acquire();
slot = await acquireSlot({
  dir: SLOT_DIR,
  max: MAX_RUNS,
  payload: { repo: REPO_ROOT, runId, tier: TIER, pid: process.pid, at: Date.now() },
  waitTimeoutMs: SLOT_TIMEOUT_MS,
  log: (line) => console.log(line),
});
console.log(
  `[e2e:run] слот семафора ${slot.index + 1}/${MAX_RUNS} занят (${SLOT_DIR}), ` +
    `клон прогона ${runId}`,
);
const startedAt = Date.now();
console.log(`[e2e:run] === ярус ${TIER}: стек мой, запускаю прогон ===`);

// БД готовим ПОД локом и слотом: `e2e:prep` поднимает Docker, ждёт его, собирает
// шаблонную БД при расхождении с репозиторием и клонирует её под этот прогон.
// Без этого прогоны падают на «БД недоступна»: стеком владеет Playwright
// (`webServer`) и Docker он больше не поднимает сам.
// Под локом — обязательно: два параллельных `e2e:prep` бьются за один Docker.
const prep = spawnSync("npm", ["run", "e2e:prep"], {
  cwd: FRONTEND_DIR,
  encoding: "utf8",
  shell: true,
  maxBuffer: 32 * 1024 * 1024,
  env: { ...process.env, E2E_RUN_ID: runId },
});
if (prep.status !== 0) {
  console.log(`[e2e:run] e2e:prep не прошёл (код ${prep.status}):`);
  console.log(`${prep.stdout ?? ""}${prep.stderr ?? ""}`.slice(-3000));
  finalize();
  process.exit(prep.status ?? 1);
}
// `prep` печатает env-файл клона — по нему backend стенда узнаёт свою БД
// (ENV_FILE уходит в `webServer`, см. `playwright.config.ts`).
runEnvFile = (prep.stdout ?? "").match(/^E2E_RUN_ENV_FILE=(.+)$/m)?.[1]?.trim() ?? null;
if (!runEnvFile || !fs.existsSync(runEnvFile)) {
  console.log(
    `[e2e:run] e2e:prep не назвал env-файл клона (E2E_RUN_ENV_FILE):\n` +
      `${prep.stdout ?? ""}`.slice(-1500),
  );
  finalize();
  process.exit(1);
}
console.log(`[e2e:run] e2e:prep ok (БД-клон прогона: ${path.basename(runEnvFile)})`);

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
    // Репортер зелёных не с первой попытки — в списке CLI, а не только в
    // конфиге: `--reporter` заменяет конфиговый список целиком, и без этой
    // строки сводка по флейкам не дошла бы ни до одного прогона отсюда.
    ...(uiMode ? [] : ["--reporter=list,./e2e/green-on-retry-reporter.ts"]),
    ...extraArgs,
  ],
  uiMode
    ? {
        cwd: FRONTEND_DIR,
        shell: false,
        stdio: "inherit",
        env: { ...process.env, E2E_ENV_FILE: runEnvFile },
      }
    : {
        cwd: FRONTEND_DIR,
        encoding: "utf8",
        shell: false,
        maxBuffer: 64 * 1024 * 1024,
        env: { ...process.env, E2E_ENV_FILE: runEnvFile },
      },
);

// В UI-режиме вывод уже ушёл в терминал как есть (`stdio: "inherit"`), а
// `result.stdout` пуст — печатать его повторно нечего.
const wall = Math.round((Date.now() - startedAt) / 1000);
if (!uiMode) {
  console.log(`${result.stdout ?? ""}${result.stderr ?? ""}`);
}
finalize();
console.log(`[e2e:run] === ярус ${TIER}: ${wall}s, код ${result.status} ===`);

// Код прогона наружу, чтобы вызывающая оболочка/агент увидел вердикт.
process.exit(result.status ?? 1);
