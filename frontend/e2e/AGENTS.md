# E2E Tests (Playwright)

Каноническое руководство по E2E в KTM-2000. Каталог: `frontend/e2e/`.

> Handoff для исполнителя (статус прогона, баги, DoD): [`docs/e2e-handoff.md`](../../docs/e2e-handoff.md)

## Два слоя тестов

| Слой | Тег | Playwright project | Назначение |
|------|-----|-------------------|------------|
| **Канон E2E** | `@ui` | `ui-e2e` | Полный пользовательский путь — только UI |
| **Smoke** | `@smoke` | `smoke` | Быстрая проверка с API-setup (не заменяет E2E) |

```bash
npm --prefix frontend run test:e2e:ui      # канон — только @ui
npm --prefix frontend run test:e2e:smoke   # smoke — API-assisted
npm --prefix frontend run test:e2e         # оба проекта
```

### @ui (канон)

- Спеки: `route-workflow.spec.ts` (эталон)
- Хелперы: [`ui-helpers.ts`](ui-helpers.ts) — seed через `/settings/dev`, импорт wizard, approve, take-to-work
- **Запрещено:** прямые `fetch` к бизнес-API (approve, import, products, …)
- Допустимо: только Playwright `page` / locators

### @smoke

- Спеки: `bulk-workflow`, `total-workflow`, `transfers-auto-accept`
- Хелперы: [`api-helpers.ts`](api-helpers.ts) — ускоренный setup через API
- Основные проверки — через UI; setup может идти через API

## Предусловия

E2E ходят в **уже запущенное** dev-окружение (`webServer` в `playwright.config.ts` закомментирован):

```bash
# из корня проекта
npm run dev
```

Отдельный терминал:

```bash
npm --prefix frontend run test:e2e:ui
npm --prefix frontend run test:e2e:smoke
npm --prefix frontend run test:e2e:playwright-ui   # Playwright UI mode (отладка)
npm --prefix frontend run test:e2e:report
```

## Переменные окружения

| Переменная | По умолчанию | Назначение |
|------------|--------------|------------|
| `PLAYWRIGHT_TEST_BASE_URL` | `http://localhost:5172` | UI (baseURL в config) |
| `E2E_API_URL` | — | Только для `@smoke`; fallback в `api-helpers.ts`: `http://localhost:8010` |

```cmd
set E2E_API_URL=http://localhost:8010/api
set PLAYWRIGHT_TEST_BASE_URL=http://localhost:5172
```

## Конфигурация

[`playwright.config.ts`](../playwright.config.ts):
- `testDir: ./e2e`
- `workers: 1`, `fullyParallel: false`
- Проекты: `ui-e2e` (`grep: /@ui/`), `smoke` (`grep: /@smoke/`)
- `retries: 2` в CI

## Фикстуры

[`fixtures.ts`](fixtures.ts):
- `authenticatedPage`, `loginAsAdmin`
- `seedTestData` — legacy; в `@ui` используйте `seedReferenceDataViaUI`

## Существующие спеки

| Файл | Тег | Сценарий |
|------|-----|----------|
| `route-workflow.spec.ts` | `@ui` | Dev seed → import → approve → execution (UI) |
| `bulk-workflow.spec.ts` | `@smoke` | Bulk-операции на shopfloor |
| `total-workflow.spec.ts` | `@smoke` | Остатки, shortage strategies |
| `transfers-auto-accept.spec.ts` | `@smoke` | Передачи, auto-accept |

## Отладка

```bash
npx playwright test --project=ui-e2e -g "import wizard" --debug
npx playwright test --project=smoke e2e/bulk-workflow.spec.ts --headed
```

Отчёт: `frontend/playwright-report/` после прогона с failures.