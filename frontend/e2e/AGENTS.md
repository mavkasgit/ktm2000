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

- Спеки: `full-cycle.spec.ts` (канонический полный цикл ЮП-009), `route-workflow.spec.ts`
- Хелперы: [`ui-helpers.ts`](ui-helpers.ts) — seed через `/settings/dev`, импорт wizard, approve, take-to-work
- **Запрещено:** прямые `fetch` к бизнес-API (approve, import, products, …)
- Допустимо: только Playwright `page` / locators

### @smoke

- Спеки: `bulk-workflow`, `total-workflow`, `transfers-auto-accept`, `final-release`, `catalog-dimensions`, `dimensions-sawing`, `plan-issue-handover`
- Хелперы: [`api-helpers.ts`](api-helpers.ts) — ускоренный setup через API
- Основные проверки — через UI; setup может идти через API

## Guard изоляции от прод-хостов

`playwright.config.ts` при старте отклоняет прогон, если `PLAYWRIGHT_TEST_BASE_URL`
или `E2E_API_URL` указывают на **публичный (боевой) хост**: проверка
`isPrivateHost` ([`src/shared/lib/hostGuard.ts`](../../frontend/src/shared/lib/hostGuard.ts))
разрешает только localhost/127.x/10.x/172.16-31.x/192.168.x/*.local.
Любой приватный адрес/порт — свободно; прод-сервер в E2E исключён.

## Шлюз перед боевым стартом

Перед первым деплоем на боевой сервер прогнать на dev зелёными:
`npm --prefix frontend run test:e2e:ui` (полный цикл ЮП-009) и
`npm --prefix frontend run test:e2e:smoke e2e/transfers-auto-accept.spec.ts`
(передача: Send → auto-accept → in_progress). Это минимально достаточный
уровень уверенности для флоу, который операторы используют ежедневно.

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
| `E2E_API_URL` | — | Только для `@smoke`; fallback в `api-helpers.ts`: `http://localhost:8012` |

```cmd
set E2E_API_URL=http://localhost:8012/api
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

| Файл | Тег | Сценарий | Статус |
|------|-----|----------|--------|
| `full-cycle.spec.ts` | `@ui` | Полный цикл ЮП-009: каталог → остатки → план → approve → запуск → маршрут → отгрузка | ✅ канон |
| `route-workflow.spec.ts` | `@ui` | Импорт-wizard диалог; legacy-кейсы полного цикла | ⚠️ частично skip (#88) |
| `transfers-auto-accept.spec.ts` | `@smoke` | Передача: Send со склада → auto-accept → `in_progress` (`received==issued`) | ✅ |
| `final-release.spec.ts` | `@smoke` | Финальный выпуск кнопкой «Отправить» (#96) | ✅ |
| `catalog-dimensions.spec.ts` | `@smoke` | Сохранение 2D/3D размеров в каталоге | ✅ |
| `dimensions-sawing.spec.ts` | `@smoke` | Доска пилы, трансформация, остатки по длинам | ⚠️ мягкие ассерции |
| `bulk-workflow.spec.ts` | `@smoke` | Bulk-операции shopfloor | ⚠️ skip (устарел, #96) |
| `total-workflow.spec.ts` | `@smoke` | Остатки, shortage strategies | ⚠️ skip (завершал складской этап с доски — переработать на передачу со склада) |
| `plan-issue-handover.spec.ts` | `@smoke` | Колонка «Размер» в плане выдачи/сдачи | ⚠️ skip (setup устарел) |

## Отладка

```bash
npx playwright test --project=ui-e2e -g "import wizard" --debug
npx playwright test --project=smoke e2e/bulk-workflow.spec.ts --headed
```

Отчёт: `frontend/playwright-report/` после прогона с failures.