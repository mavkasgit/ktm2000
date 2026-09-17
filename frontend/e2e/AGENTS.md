# E2E Tests (Playwright)

Каноническое руководство по E2E в KTM-2000. Каталог: `frontend/e2e/`.

## Слои тестов

| Слой | Тег | Playwright project | Назначение |
|------|-----|-------------------|------------|
| **Канон E2E** | `@ui` | `ui-e2e` | Бизнес-путь через UI; сетап данных — API/визарды |
| **Smoke** | `@smoke` | `smoke` | Быстрая проверка с API-setup (не заменяет E2E) |
| **Временные** | `@tmp` | `tmp` (только при `E2E_TMP=1`) | Разовый прогон; в регулярный набор не входит |

```bash
npm --prefix frontend run test:e2e:ui      # канон — только @ui
npm --prefix frontend run test:e2e:smoke   # smoke — API-assisted
npm --prefix frontend run test:e2e         # оба проекта
```

### @ui (канон)

- Спеки: `full-cycle.spec.ts` (канонический полный цикл ЮП-009), `route-workflow.spec.ts`,
  `sawing-four-lengths-cycle.spec.ts` (пила в полном цикле: раскрой 2,75 м на четыре длины),
  `single-line-cycle.spec.ts` (одна строка плана: сквозной маршрут передачи ↔ участки до «Отправлено»),
  `sawing-multi-length-split.spec.ts` (распил задачи на разные длины),
  `yup460-shared-raw-pile.spec.ts` (три варианта ЮП-460 делят одну кучу сырья)
- Хелперы: [`ui-helpers.ts`](ui-helpers.ts) — seed через `/settings/dev`, approve,
  take-to-work, чтение журнала передач; [`api-helpers.ts`](api-helpers.ts) — бесфайловый сетап.
- Сетап данных — обычно через API ([`api-helpers.ts`](api-helpers.ts)): артикул
  (`apiEnsureCatalogProduct`), остаток (`apiAddRemainder`), план
  (`apiSimulatePlanImport` → `POST /api/imports/excel/simulate`, без xlsx).
  В кадре — бизнес-действия UI (approve, запуск, передачи, завершение задач).
- **Запрещено** в бизнес-шагах: прямые `fetch` к бизнес-API (approve, take-to-work, передачи).
- Живые xlsx-импорты — только в `full-cycle.spec.ts` (каталог + остатки) и
  `route-workflow.spec.ts` (план); остальные сетапятся бесфайлово (см. «xlsx-фикстуры»).

### xlsx-фикстуры

По одному основному варианту на вид импорта, всё в [`testdata/`](testdata/):

| Файл | Что | Живой UI-импорт в |
|------|-----|-------------------|
| `Упаковочный план.xlsx` | главный план (~318 строк, десятки артикулов) | `route-workflow.spec.ts` |
| `Каталог E2E.xlsx` | справочник сырья ЮП-009 | `full-cycle.spec.ts` |
| `Склад импорта остатков E2E.xlsx` | остатки ЮП-009 на «Склад сырья» | `full-cycle.spec.ts` |

Остальные сценарии эти виды данных **не хранят**: план — `apiSimulatePlanImport`
(строки в теле запроса, workbook собирается на бэкенде в памяти и идёт обычным
change-set); каталог/остатки — прямые вызовы API (`apiEnsureCatalogProduct`,
`apiAddRemainder`). Отдельные e2e-xlsx под ЮП-2083/ЮП-4610 удалены — не плодим файлы.

Файлы в `testdata/` остаются локальными (`*.xlsx` в `.gitignore`) — как и прежние фикстуры.

### @smoke

- Спеки: `transfers-auto-accept`, `final-release`, `catalog-dimensions`, `dimensions-sawing`, `reversal-journal`
- Хелперы: [`api-helpers.ts`](api-helpers.ts) — ускоренный setup через API
- Основные проверки — через UI; setup может идти через API

### @tmp (временные, разовые)

- Инструмент отладки/разовой проверки, а не часть набора: файл называется
  `*.tmp.spec.ts`, тег `@tmp`, в шапке — что и зачем проверяем и с чем удалять.
- Проекта `tmp` нет, пока не задан `E2E_TMP` → `test:e2e`, `test:e2e:ui`,
  `test:e2e:smoke` такие спеки не трогают.
- Запуск разово:
  ```bash
  cd frontend && E2E_TMP=1 npx playwright test --project=tmp e2e/<file>.tmp.spec.ts
  ```
- Задача закрыта → спека и её фикстуры удаляются (одноразовый артефакт).

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
| `full-cycle.spec.ts` | `@ui` | Полный цикл ЮП-009: каталог и остатки — живой импорт через UI-визарды, план — сетап API (без xlsx) → approve → запуск → маршрут → отгрузка | ✅ канон |
| `route-workflow.spec.ts` | `@ui` | Реальный импорт главного «Упаковочного плана» (xlsx через UI-визард) + инфо о маршруте в таблице плана | ✅ |
| `single-line-cycle.spec.ts` | `@ui` | Одна строка плана (ЮП-009, сетап API) → approve → запуск → цикл «передачи ↔ участки»: цепочка адресатов читается из журнала передач (включая складские секции), задача завершается на текущем участке, до «Отправлено» | ✅ |
| `sawing-multi-length-split.spec.ts` | `@ui` | Пила: распил одной задачи на несколько разных длин (2,7 м → 0,9 м + 1,8 м) порциями через доску; ledger + остатки по длинам. Сетап — API (план без xlsx), в кадре только действие участка | ✅ |
| `sawing-four-lengths-cycle.spec.ts` | `@ui` | Пила в полном цикле (ЮП-2083): каталог/остатки (2,75 м)/план из 4 позиций (ГП-раскрой 2,7 м → 0,9 + 1,35 + 1,8 + 2,7, П/ф 2,7, ГП одиночный 1,35, ГП без резки) — сетап API (без xlsx) → approve → запуск → маршрут с двумя порциями на пиле → отгрузка. Дальше только UI | ✅ |
| `yup460-shared-raw-pile.spec.ts` | `@ui` | ЮП-460: окно / гребенка / без пресса делят одну кучу сырья; план из 3 строк — сетап API (без xlsx) | ✅ |
| `transfers-auto-accept.spec.ts` | `@smoke` | Передача: Send со склада → auto-accept → `in_progress` (`received==issued`); план — сетап API (без xlsx) | ✅ |
| `final-release.spec.ts` | `@smoke` | Финальный выпуск кнопкой «Отправить» (#96) | ✅ |
| `catalog-dimensions.spec.ts` | `@smoke` | Сохранение 2D/3D размеров в каталоге | ✅ |
| `dimensions-sawing.spec.ts` | `@smoke` | Доска пилы, трансформация, остатки по длинам | ⚠️ мягкие ассерции |
| `reversal-journal.spec.ts` | `@smoke` | Отмена действий (#117): страница `/reversal`, журнал и дерево цепочки | ✅ |

## Отладка

```bash
npx playwright test --project=ui-e2e -g "import wizard" --debug
npx playwright test --project=smoke e2e/reversal-journal.spec.ts --headed
```

Отчёт: `frontend/playwright-report/` после прогона с failures.