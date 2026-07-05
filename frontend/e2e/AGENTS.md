# E2E Tests (Playwright)

Каноническое руководство по E2E в KTM-2000. Каталог: `frontend/e2e/`.

> Handoff для исполнителя (статус прогона, баги, DoD): [`docs/e2e-handoff.md`](../../docs/e2e-handoff.md)

## Предусловия

E2E ходят в **уже запущенное** dev-окружение (webServer в `playwright.config.ts` закомментирован):

```bash
# из корня проекта
npm run dev
```

Отдельный терминал:

```bash
npm --prefix frontend run test:e2e          # headless Chromium
npm --prefix frontend run test:e2e:ui     # UI-режим Playwright
npm --prefix frontend run test:e2e:report # отчёт последнего прогона
```

Один файл:

```bash
cd frontend
npx playwright test e2e/route-workflow.spec.ts
npx playwright test e2e/bulk-workflow.spec.ts --headed
```

## Переменные окружения

| Переменная | По умолчанию | Назначение |
|------------|--------------|------------|
| `PLAYWRIGHT_TEST_BASE_URL` | `http://localhost:5180` | UI (baseURL в config) |
| `E2E_API_URL` | — | Прямые API-вызовы в тестах; fallback в спеках: `http://localhost:8082` |

> Для локального dev с backend на `:8010` задайте `E2E_API_URL=http://localhost:8010/api` перед запуском.

## Конфигурация

[`playwright.config.ts`](../playwright.config.ts):
- `testDir: ./e2e`
- `workers: 1`, `fullyParallel: false` — тесты идут последовательно
- `retries: 2` в CI
- `trace` / `screenshot` / `video` — при падении
- Проект: `chromium` (Desktop Chrome)

## Фикстуры

[`fixtures.ts`](fixtures.ts) — расширение `test`:
- `authenticatedPage` — логин `admin@ktm2000.local` / `admin` (если не `DEV_BYPASS_AUTH`)
- `loginAsAdmin` — хелпер повторного логина
- `seedTestData` — POST `/api/routes/seed` через page.evaluate

Импорт в спеках: `import { test, expect } from "./fixtures"`.

## Существующие спеки

| Файл | Сценарий |
|------|----------|
| `route-workflow.spec.ts` | Импорт Excel → план → approve → release → execution |
| `bulk-workflow.spec.ts` | Bulk-операции на участках, групповые передачи |
| `total-workflow.spec.ts` | Seed остатков, полный workflow |
| `transfers-auto-accept.spec.ts` | Передачи, auto-accept |

## Паттерны в спеках

- **UI** — через `page` (Playwright locators: `getByRole`, `getByLabel`).
- **Setup через API** — `fetch` к `BACKEND_URL` (seed, approve, release) для ускорения.
- **Не полагайтесь на фиксированные ID** — читайте из ответов API.
- Селекторы — role/label/text, не хрупкие CSS-классы.

## Отладка

```bash
npx playwright test e2e/route-workflow.spec.ts --debug
npx playwright test e2e/route-workflow.spec.ts --trace on
```

Отчёт HTML: `frontend/playwright-report/` после прогона с failures.