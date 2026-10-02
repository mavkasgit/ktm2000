/**
 * Обёртка прогона E2E: сама выбирает свободные порты стенда и только потом
 * запускает `playwright test`.
 *
 * ## Зачем
 * Раньше порты стенда были константами (`.env.e2e`: 8013/5173). Любой
 * прерванный прогон или чужой процесс оставлял порт в LISTENING, и следующий
 * прогон падал на `http://127.0.0.1:8013/api/health is already used` — то
 * есть на чужом мусоре, а не на своей проверке. Обойти это можно было только
 * ручным переопределением двух переменных в командной строке.
 *
 * Здесь порты берутся у ОС (`listen(0)` → свободный порт) на каждый прогон:
 * статики нет, конфликт со старым прогоном невозможен по построению. Порты
 * передаются дальше теми же переменными (`E2E_API_URL`,
 * `PLAYWRIGHT_TEST_BASE_URL`), поэтому конфиг Playwright, хелперы и
 * `api-helpers` ничего не знают о подмене — меняется только значение.
 *
 * ## Когда не подменять
 *
 * Если `E2E_API_URL` или `PLAYWRIGHT_TEST_BASE_URL` уже заданы в окружении
 * (прогон против стенка, поднятого руками, — `PW_REUSE_STACK=1`), значения
 * оставляются как есть: там стек чужой, и его адреса менять нельзя.
 *
 * ## CORS
 *
 * `CORS_ORIGINS` в `.env.e2e` не задан: origin frontend на стенде заранее
 * неизвестен. Обычный путь UI идёт через vite-прокси и CORS не касается, но
 * адрес всё равно должен соответствовать реально поднятому frontend, поэтому
 * обёртка дописывает выбранный origin в переменную окружения — она важнее
 * файла. Иначе прямой запрос из теста получил бы CORS-ошибку на пустом месте.
 */
import { createServer } from "node:net";
import { spawn } from "node:child_process";
import { fileURLToPath } from "node:url";
import path from "node:path";

/** @returns {Promise<number>} свободный порт, выданный ОС */
function freePort() {
  return new Promise((resolve, reject) => {
    const server = createServer();
    server.unref();
    server.on("error", reject);
    server.listen(0, "127.0.0.1", () => {
      const address = server.address();
      server.close(() => {
        if (address === null || typeof address === "string") {
          reject(new Error("ОС не вернула порт для стенда E2E"));
          return;
        }
        resolve(address.port);
      });
    });
  });
}

const env = { ...process.env };

// Сколько воркеров Playwright в прогоне: столько же backend'ов и клонов БД
// (#289). `run-tier.mjs` знает `--workers` и передаёт его через `E2E_WORKERS`.
const WORKERS = Math.max(1, Number(env.E2E_WORKERS ?? 1) || 1);

if (!env.E2E_API_URL || !env.PLAYWRIGHT_TEST_BASE_URL) {
  // Портов нужно WORKERS + 2: по backend'у на воркера, плюс frontend и роутер
  // `/api`, который выбирает backend по заголовку `x-e2e-worker`
  // (`scripts/e2e-api-router.mjs`).
  const ports = await Promise.all(Array.from({ length: WORKERS + 2 }, freePort));
  const [backendPorts, routerPort, frontendPort] = [
    ports.slice(0, WORKERS),
    ports[WORKERS],
    ports[WORKERS + 1],
  ];
  const frontendOrigin = `http://127.0.0.1:${frontendPort}`;
  const workerApiUrls = backendPorts.map((port) => `http://127.0.0.1:${port}/api`);
  // `E2E_API_URL` — воркер 0: одиночный прогон и прямые вызовы из Node
  // (`api-helpers.ts`) ходят по нему без заголовка.
  env.E2E_API_URL ??= workerApiUrls[0];
  env.PLAYWRIGHT_TEST_BASE_URL ??= frontendOrigin;
  // Воркерные адреса нужны и роутеру, и backend'ам конфига (`webServer`).
  env.E2E_WORKER_API_URLS = JSON.stringify(workerApiUrls);
  env.E2E_ROUTER_PORT = String(routerPort);
  // CORS проверяет Origin, а не Host, поэтому нужны оба написания адреса.
  // В `.env.e2e` CORS_ORIGINS намеренно не задан (origin заранее неизвестен),
  // а переменная окружения важнее файла — сюда попадает ровно то, что нужно.
  env.CORS_ORIGINS = [frontendOrigin, `http://localhost:${frontendPort}`]
    .concat((env.CORS_ORIGINS ?? "").split(",").filter(Boolean))
    .join(",");
  console.log(
    `[e2e:ports] стенд на свободных портах: frontend ${frontendPort}, ` +
      `роутер /api ${routerPort}, backend ${backendPorts.join(", ")}` +
      (WORKERS > 1 ? ` (воркеров: ${WORKERS})` : ""),
  );
}

// Роутер `/api` живёт ровно столько же, сколько прогон: его поднимаем здесь и
// снимаем вместе с Playwright (в том числе по SIGINT/SIGTERM — иначе после
// отмены прогона порт остался бы в LISTENING, а это ровно тот мусор, ради
// которого обёртка и выдаёт порты заново на каждый запуск).
//
// При `PW_REUSE_STACK=1` (ручной стенд) адреса backend'ов не выдавались —
// роутер не поднимаем, `/api` у стенда и так один.
let router = null;
if (env.E2E_WORKER_API_URLS) {
  const routerCli = fileURLToPath(new URL("./e2e-api-router.mjs", import.meta.url));
  router = spawn(process.execPath, [routerCli], { stdio: "inherit", env });
  router.on("error", (error) => {
    console.error(`[e2e:ports] роутер /api не поднялся: ${error.message}`);
    process.exit(1);
  });
}

function stopRouter() {
  router?.kill();
}
process.on("exit", stopRouter);
for (const sig of ["SIGINT", "SIGTERM"]) {
  process.on(sig, stopRouter);
}

const frontendDir = fileURLToPath(new URL("..", import.meta.url));
const playwrightCli = path.join(frontendDir, "node_modules", "@playwright", "test", "cli.js");

const child = spawn(process.execPath, [playwrightCli, "test", ...process.argv.slice(2)], {
  cwd: frontendDir,
  stdio: "inherit",
  env,
});

child.on("exit", (code, signal) => {
  if (signal) {
    process.kill(process.pid, signal);
    return;
  }
  process.exit(code ?? 0);
});
