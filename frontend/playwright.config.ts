import { defineConfig, devices } from "@playwright/test";
import { isPrivateHost } from "./src/shared/lib/hostGuard";

const PORT = 5172;
const BACKEND_PORT = 8012;

const baseURL = process.env.PLAYWRIGHT_TEST_BASE_URL || `http://localhost:${PORT}`;
const e2eApiUrl = process.env.E2E_API_URL;

for (const [name, value] of [
  ["PLAYWRIGHT_TEST_BASE_URL", baseURL],
  ["E2E_API_URL", e2eApiUrl ?? ""],
]) {
  if (value && !isPrivateHost(value)) {
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
const backendPort = Number(e2eApiUrl?.match(/:(\d+)/)?.[1] ?? 8012);

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
          // поднимает.
          command: "npm --prefix .. run backend",
          url: `http://127.0.0.1:${backendPort}/api/health`,
          reuseExistingServer: false,
          timeout: 120_000,
          stdout: "pipe" as const,
          stderr: "pipe" as const,
        },
        {
          command: "npm run dev",
          url: `http://127.0.0.1:${frontendPort}/`,
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
