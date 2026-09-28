import { readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import { defineConfig, devices } from "@playwright/test";
import { isPrivateHost } from "./src/shared/lib/hostGuard";

// Стенд E2E — отдельная БД и отдельные порты (#220). Источник правды для
// них — `.env.e2e` в корне репозитория (та же БД, что поднимает `e2e:prep`),
// а не константы этого файла: прогон против чужого стека переопределяет
// значения переменными окружения, и они важнее содержимого файла.
const STAND_ENV_FILE = fileURLToPath(new URL("../.env.e2e", import.meta.url));

function loadStandEnv(file: string): void {
  let content: string;
  try {
    content = readFileSync(file, "utf8");
  } catch {
    throw new Error(
      `Не найден env-файл стенда ${file}: без него прогон не знает свою БД и порты.`,
    );
  }
  for (const line of content.split(/\r?\n/)) {
    const match = /^\s*([A-Za-z_][A-Za-z0-9_]*)\s*=\s*(.*?)\s*$/.exec(line);
    if (!match) continue;
    const [, key, value] = match;
    if (process.env[key] === undefined) {
      process.env[key] = value.replace(/^["']|["']$/g, "");
    }
  }
}

loadStandEnv(STAND_ENV_FILE);

const baseURL = process.env.PLAYWRIGHT_TEST_BASE_URL!;
const e2eApiUrl = process.env.E2E_API_URL!;

for (const [name, value] of [
  ["PLAYWRIGHT_TEST_BASE_URL", baseURL],
  ["E2E_API_URL", e2eApiUrl],
] as const) {
  if (!value) {
    throw new Error(
      `${name} не задан: адреса стенда берутся из env-файла ${STAND_ENV_FILE} ` +
        "(или задай переменную сам).",
    );
  }
  if (!isPrivateHost(value)) {
    throw new Error(
      `${name}=${value} указывает на публичный (боевой) хост. E2E запрещено гонять против прод-окружения.`,
    );
  }
}
// Владение dev-стеком — у Playwright, а не у собственных setup/teardown.
//
// Что было: `globalSetup` поднимал `npm run dev` через
// `spawn(..., { detached: true, shell: true })` и тут же терял владение
// процессом, а `globalTeardown` угадывал, что убивать, по регуляркам в
// command line. С uvicorn --reload это давало сироту
// `python scripts/dev_server.py`: порт :8012 оставался в LISTENING с
// мёртвым воркером, и следующий прогон падал на «Тест-стек недоступен» —
// выглядело как баг приложения, а было следствием уборки.
//
// Что стало: Playwright сам стартует backend и frontend, сам ждёт готовности
// и сам убивает своё дерево по завершении прогона (на Windows — вместе с
// reloader'ом). Угадывать, чей это процесс, больше не нужно.
//
// Молчаливое подхватывание чужого стека запрещено: чужой процесс может быть
// старше рабочего дерева, и E2E поедет против старого бэкенда. Для отладки
// с уже поднятым стеком — явный `PW_REUSE_STACK=1`.
const reuseStack = process.env.PW_REUSE_STACK === "1";
const localStack = /^localhost$|^127\./.test(new URL(baseURL).hostname);
if (!localStack && !reuseStack) {
  throw new Error(
    `PLAYWRIGHT_TEST_BASE_URL=${baseURL} указывает не на локальную машину: ` +
      "Playwright не поднимет стек для удалённого хоста. Либо гоняй против " +
      "localhost, либо поставь PW_REUSE_STACK=1, если стек поднят руками.",
  );
}
const frontendPort = Number(new URL(baseURL).port || 5172);
const backendPort = Number(new URL(e2eApiUrl).port || 8012);

export default defineConfig({
  testDir: "./e2e",
  fullyParallel: false,
  forbidOnly: !!process.env.CI,
  retries: process.env.CI ? 2 : 0,
  workers: 1,
  reporter: [["html", { outputFolder: "playwright-report" }], ["list"]],
  use: {
    baseURL,
    trace: "on-first-retry",
    // Скриншот снимается всегда, а не только при падении: при остановке
    // прогона (окно headed, пауза, падение) остаётся картинка, по которой
    // видно, на каком экране тест остановился.
    screenshot: "on",
    video: "retain-on-failure",
  },
  webServer: reuseStack
    ? undefined
    : [
        {
          // БД поднимается до прогона (`npm run e2e:prep`): `webServer`
          // стартует команды параллельно, а `npm run backend` сам Docker не
          // поднимает. ENV_FILE уводит backend на БД стенда (`.env.e2e`),
          // а не на общую dev-БД из `.env.dev`; BACKEND_PORT — на порт стенда,
          // чтобы стек не делил 8012 с работающим devstack.
          command: "npm --prefix .. run backend",
          url: `http://127.0.0.1:${backendPort}/api/health`,
          env: { ENV_FILE: STAND_ENV_FILE, BACKEND_PORT: String(backendPort) },
          reuseExistingServer: false,
          timeout: 120_000,
          stdout: "pipe" as const,
          stderr: "pipe" as const,
        },
        {
          // Порт стенда задаётся аргументами vite: в конфиге он зашит на 5172
          // (LAN-ссылки devstack), а стенд идёт на своём. VITE_PROXY_TARGET
          // уводит /api на backend стенда, иначе UI ходил бы в чужой.
          command: `npm run dev -- --port ${frontendPort} --strictPort`,
          url: `http://127.0.0.1:${frontendPort}/`,
          env: { VITE_PROXY_TARGET: `http://127.0.0.1:${backendPort}` },
          reuseExistingServer: false,
          timeout: 120_000,
          stdout: "pipe" as const,
          stderr: "pipe" as const,
        },
      ],
  // Уборка после прогона: только осиротевшие браузеры/проигрыватели ЭТОГО
  // прогона. Стек убирает Playwright (`webServer`), порты трогать нельзя:
  // при `PW_REUSE_STACK=1` чужой стек должен пережить прогон.
  // Teardown не бросает исключений, чтобы не замаскировать падение теста.
  globalTeardown: "./e2e/global-teardown.ts",
  // Порядок прогонов — от общего к узкому, с fail-fast между ярусами.
  //
  // Почему так, а не «как получится»: без зависимостей Playwright выполняет
  // проекты в порядке объявления и НЕ останавливается на первом упавшем ярусе
  // — упавший smoke всё равно утянул бы за собой 15 минут @ui-прогона. С
  // `dependencies` проект ставится в отдельную фазу (runner/index.js:6047) и
  // при падении зависимости пропускается целиком (runner/index.js:6088),
  // поэтому первый сломанный ярус виден сразу, а не через полчаса.
  //
  // Ярусы:
  //  1. `smoke`     — быстрые проверки с API-сетапом; ломается всё → стоп.
  //  2. `ui-e2e`    — широкие бизнес-циклы через UI (полный цикл, импорт,
  //                   одна строка плана). Читает то, что проверяет smoke.
  //  3. `ui-narrow` — узкие доменные сценарии (пила, ЮП-460): долгие,
  //                   зависят от всего предыдущего. Запускаются последними.
  //
  // Фильтр `--project=ui-e2e` подтягивает зависимости автоматически, поэтому
  // `test:e2e:ui` остаётся шлюзом «прогнать @ui зелёным».
  projects: [
    {
      name: "smoke",
      grep: /@smoke/,
      use: { ...devices["Desktop Chrome"] },
    },
    {
      name: "ui-e2e",
      grep: /@ui/,
      // `@ui-narrow` — тоже `@ui`, без инверта спека попала бы в оба яруса
      // и прогонялась дважды.
      grepInvert: /@ui-narrow/,
      timeout: 120_000,
      dependencies: ["smoke"],
      use: { ...devices["Desktop Chrome"] },
    },
    {
      name: "ui-narrow",
      grep: /@ui-narrow/,
      timeout: 120_000,
      dependencies: ["ui-e2e"],
      use: { ...devices["Desktop Chrome"] },
    },
    // Разовые (временные) спеки с тегом `@tmp`: в регулярных прогонах не
    // участвуют — проекта нет, пока не задан `E2E_TMP`. Вне цепочки
    // зависимостей: отладка одного сценария не должна гонять весь набор.
    // Запуск: E2E_TMP=1 npx playwright test --project=tmp e2e/<file>.tmp.spec.ts
    ...(process.env.E2E_TMP
      ? [
          {
            name: "tmp",
            grep: /@tmp/,
            use: { ...devices["Desktop Chrome"] },
          },
        ]
      : []),
  ],
  // webServer: [
  //   {
  //     command: `cd ../backend && poetry run uvicorn app.main:app --host 0.0.0.0 --port ${BACKEND_PORT}`,
  //     url: `http://localhost:${BACKEND_PORT}/api/health`,
  //     reuseExistingServer: true,
  //     timeout: 30_000,
  //   },
  //   {
  //     command: "npm run dev",
  //     url: `http://localhost:${PORT}`,
  //     reuseExistingServer: true,
  //     timeout: 30_000,
  //   },
  // ],
});
