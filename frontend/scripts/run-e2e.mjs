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

if (!env.E2E_API_URL || !env.PLAYWRIGHT_TEST_BASE_URL) {
  const [backendPort, frontendPort] = await Promise.all([freePort(), freePort()]);
  const frontendOrigin = `http://127.0.0.1:${frontendPort}`;
  env.E2E_API_URL ??= `http://127.0.0.1:${backendPort}/api`;
  env.PLAYWRIGHT_TEST_BASE_URL ??= frontendOrigin;
  // CORS проверяет Origin, а не Host, поэтому нужны оба написания адреса.
  // В `.env.e2e` CORS_ORIGINS намеренно не задан (origin заранее неизвестен),
  // а переменная окружения важнее файла — сюда попадает ровно то, что нужно.
  env.CORS_ORIGINS = [frontendOrigin, `http://localhost:${frontendPort}`]
    .concat((env.CORS_ORIGINS ?? "").split(",").filter(Boolean))
    .join(",");
  console.log(
    `[e2e:ports] стенд на свободных портах: backend ${backendPort}, frontend ${frontendPort}`,
  );
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
