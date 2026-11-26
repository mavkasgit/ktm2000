# E2E: переменные окружения и конфигурация Playwright

Справочник к [`frontend/e2e/AGENTS.md`](../../frontend/e2e/AGENTS.md).

**Когда читать:** нужна переменная, которой нет под рукой; прогон ведёт себя
иначе из-за `CI`/`PW_REUSE_STACK`/`E2E_*`; проверяете `playwright.config.ts`
(проекты, ретраи, репортёры, таймауты, `webServer`).

## Переменные окружения

Дефолты берутся из [`.env.e2e`](../../.env.e2e) — конфиг читает файл при
старте и **не перекрывает** уже заданные переменные окружения. На деле адреса
задаёт обёртка [`frontend/scripts/run-e2e.mjs`](../../frontend/scripts/run-e2e.mjs): она подставляет
свободные порты ОС ДО запуска `playwright test`, поэтому в таблице — только
значения для прогона против стенка, поднятого руками.

| Переменная | Откуда берётся | Назначение |
|------------|--------------|------------|
| `PLAYWRIGHT_TEST_BASE_URL` | обёртка (`listen(0)`) — в `.env.e2e` адреса **нет** | UI (`baseURL`) и порт frontend в `webServer` |
| `E2E_API_URL` | обёртка (`listen(0)`) — в `.env.e2e` адреса **нет** | API для `@smoke`; в конфиге — ещё и порт backend в `webServer` |
| `E2E_TEST_DATABASE_URL` | DSN клона прогона (`<база>_run_<stamp>_<run-id>` на `:5441`) | БД стенда для `ensureDbBootstrapped` (достраивает справочники сам) |
| `PW_REUSE_STACK` | — | `1` — стек поднят руками, Playwright его не трогает и не поднимает свой |
| `E2E_WORKERS` | `run-tier.mjs` (из `--workers`, иначе `DEFAULT_WORKERS` = 2) | сколько воркеров Playwright, клонов БД и backend'ов стенда (#289, #376); конфиг читает то же число, поэтому прямой вызов `run-e2e.mjs` не разъедется с числом backend'ов. В CI-джобе `e2e smoke` — `1`: БД одна |
| `E2E_SKIP_PASSED` | — | `1` — пропускать тесты, уже прошедшие на этой версии кода |
| `E2E_MAX_PARALLEL_RUNS` | — | сколько e2e-прогонов пускать на машине одновременно (по умолчанию 2) |
| `E2E_SEMAPHORE_DIR` | — | каталог слотов семафора; по умолчанию `%LOCALAPPDATA%\ktm2000-e2e\slots` |
| `E2E_SEMAPHORE_TIMEOUT_MS` | — | сколько ждать свободный слот (по умолчанию 30 мин) |
| `E2E_RUN_ID` | — | id клона БД; иначе случайный (`run-tier.mjs` генерирует сам) |
| `E2E_STALE_RUN_MINUTES` | — | возраст, после которого клон брошенного прогона сносится `prep`/`drop` (180) |
| `E2E_DB_KEEP` | — | `1` — `scripts/e2e-db.py ensure` печатает причину расхождения БД стенда с репозиторием, но не пересоздаёт её (то же, что `--keep`) |
| `E2E_TEMPLATE_KEEP` | — | `1` — не пересобирать расходящийся шаблон, только напечатать причину (то же, что `--keep-template`) |
| `CI` | харнесс выставляет `CI=true` | **переопредели явным пустым значением** (`CI='' npm …`): `unset CI` не помогает, а при непустом `CI` конфиг даёт `retries: 2` и флейки выглядят зелёными |

```cmd
REM прогон против уже поднятого devstack
set E2E_API_URL=http://localhost:8012/api
set PLAYWRIGHT_TEST_BASE_URL=http://localhost:5172
set PW_REUSE_STACK=1
set E2E_SKIP_PASSED=1
```

## Конфигурация

[`playwright.config.ts`](../../frontend/playwright.config.ts):

- `testDir: ./e2e`
- `workers: DEFAULT_WORKERS` (`2`, значение — в
  [`run-workers.mjs`](../../frontend/e2e/run-workers.mjs); `PW_REUSE_STACK=1` — 1), `fullyParallel: false`
- `retries: process.env.CI ? 2 : 0` — локально ретраев нет ни одного
- `forbidOnly: !!process.env.CI`
- `reporter`: `html` (в `playwright-report/`) + `list` +
  [`green-on-retry-reporter.ts`](../../frontend/e2e/green-on-retry-reporter.ts) (зелёные не с
  первой попытки — см. [`pass-cache.md`](pass-cache.md))
- `use`: `baseURL` из `PLAYWRIGHT_TEST_BASE_URL`, `trace: "on-first-retry"`,
  `screenshot: "on"` (снимок всегда, а не только при падении),
  `video: "retain-on-failure"`
- Проекты (порядок и fail-fast — через `dependencies`; все `grep`/`grepInvert`
  собирает `tagRe` из `e2e/mobile-project.mjs`, тег матчится как токен):
  `smoke` (`grep: tagRe("@smoke")`, `grepInvert: MOBILE_TAG_RE`, таймаут
  дефолтный 30 c) → `ui-e2e` (`grep: tagRe("@ui")`,
  `grepInvert: tagRe("@ui-narrow", "@mobile")`, `timeout: 120_000`, зависит от
  `smoke`) → `ui-narrow` (`grep: tagRe("@ui-narrow")`,
  `grepInvert: MOBILE_TAG_RE`, `timeout: 120_000`, зависит от `ui-e2e`) →
  `mobile` (`grep: MOBILE_TAG_RE`,
  окно 390×844 + `isMobile`/`hasTouch`/`deviceScaleFactor: 2` из
  `e2e/mobile-project.mjs`, без `dependencies` — мобильный ярус вне цепочки)
  → `tmp` (`grep: tagRe("@tmp")`, таймаут дефолтный), только при заданном `E2E_TMP`
  и вне цепочки зависимостей
- `webServer`: `npm --prefix .. run backend`
  (`http://127.0.0.1:<порт>/api/health`) и `npm run dev`
  (`http://127.0.0.1:<порт>/`), у обоих `reuseExistingServer: false` и
  `timeout: 120_000`; при `PW_REUSE_STACK=1` `webServer` не задаётся вовсе
- `globalTeardown: ./e2e/global-teardown.ts`; `globalSetup` в конфиге нет —
  стек поднимает `webServer`
