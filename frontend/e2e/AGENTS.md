# E2E Tests (Playwright)

Каноническое руководство по E2E в KTM-2000. Каталог: `frontend/e2e/`.

## Слои тестов и порядок прогона

Прогон разбит на три яруса — **от общего к узкому**. Каждый следующий ярус
зависит от предыдущего (`dependencies` в `playwright.config.ts`), поэтому
первый сломанный ярус останавливает прогон, а не отрабатывает вхолостую
через полчаса.

| Ярус | Тег | Playwright project | Зависит от | Назначение |
|------|-----|-------------------|-----------|------------|
| 1. Smoke | `@smoke` | `smoke` | — | Быстрая проверка с API-setup. Сломалось здесь — дальше идти незачем |
| 2. Широкий UI | `@ui` | `ui-e2e` | `smoke` | Бизнес-путь через UI; сетап данных — API/визарды |
| 3. Узкий UI | `@ui-narrow` | `ui-narrow` | `ui-e2e` | Доменные сценарии (пила, ЮП-460): долгие, зависят от всего предыдущего |
| Временные | `@tmp` | `tmp` (только при `E2E_TMP=1`) | — | Разовый прогон; вне цепочки зависимостей |

`@ui-narrow` — подмножество `@ui`: такие спеки помечены **обоими** тегами в
`test.describe`, а `ui-e2e` исключает их через `grepInvert`, иначе спека
прогонялась бы дважды.

```bash
npm --prefix frontend run test:e2e:smoke   # только 1-й ярус
npm --prefix frontend run test:e2e:ui      # ярусы 1+2 (2 подтягивает 1)
npm --prefix frontend run test:e2e:ui:narrow  # все три (3 тянет 1 и 2)
npm --prefix frontend run test:e2e         # все проекты подряд
```

Фильтр `--project` подтягивает зависимости автоматически, так что
`test:e2e:ui` — по-прежнему шлюз «прогнать @ui зелёным», просто теперь с
коротким smoke-шлюзом перед ним.

**В какой ярус попадает новая спека:** спрашивайте «насколько это широко».
Проверяет общий бизнес-путь (цикл, импорт, маршрут) — `@ui`. Проверяет один
доменный сценарий на конкретном артикуле (пила, ЮП-460) — `@ui-narrow`.

### Сколько занимает каждый ярус

Замер 27.09.2026, `npx playwright test --project=<ярус> --no-deps --reporter=list`
(только время самих тестов, без `globalSetup` — перезапуск dev-стека занимает
ещё 1–2 мин поверх этого).

| Тест | Время |
|------|-------|
| `dimensions-sawing` — API остатков по группам | **0.3s** |
| `reversal-journal` | 6.8s |
| `dimensions-sawing` — доска пилы | 6.4s |
| `final-release` | 7.7s |
| `route-workflow` — визард импорта | 8.7s |
| `yup460-shared-raw-pile` | 13.2s |
| `catalog-dimensions` | 16.5s |
| `route-workflow` — маршрут в плане | 21.4s |
| `transfers-auto-accept` | ~30s |
| `sawing-four-lengths-cycle` | ~30–45s (с ретраем) |
| `full-cycle` | ~36s |

Итого по ярусам: **smoke ≈ 1 мин, ui-e2e ≈ 1–2 мин, ui-narrow ≈ 1 мин**.
Полный прогон `test:e2e` — около **5–7 минут** вместе с тремя перезапусками
стека (по одному на ярус).

**Не ориентируйтесь на эти числа как на эталон.** Здесь они полезны только для
выбора, что гонять в первую очередь при правке: дешёвое — в пределах
10–20 секунд, дорогое — 30+. Но фактическое время сильно плывёт: те же тесты
в разных прогонах отличались в 2–3 раза (например, `dimensions-sawing` — 5.5s
и 6.4s, `transfers-auto-accept` — 16s зелёным и ~30s красным), потому что
время сильно зависит от прогрева бэкенда и от того, на каком тесте стек
упал. Замерять свои значения: `npx playwright test --project=ui-e2e --no-deps
--reporter=list`.

Отдельно: `--no-deps` нужен, чтобы замерить **все** ярусы подряд. Без него
fail-fast остановит прогон на первом красном ярусе, и хвост не измерится.

### Канон `@ui` и `@ui-narrow`

- Ярус 2 (`@ui`): `full-cycle.spec.ts` (канонический полный цикл ЮП-009),
  `route-workflow.spec.ts`, `single-line-cycle.spec.ts` (одна строка плана:
  сквозной маршрут передачи ↔ участки до «Отправлено»).
  `approve-freshness.spec.ts` (свежесть: позиция, утверждённая на плане, видна
  на «Контроле выполнения» без перезагрузки — одиночным и массовым путём).
- Ярус 3 (`@ui-narrow`): `sawing-four-lengths-cycle.spec.ts` (пила в полном
  цикле: раскрой 2,75 м на четыре длины), `sawing-multi-length-split.spec.ts`
  (распил задачи на разные длины), `yup460-shared-raw-pile.spec.ts` (три
  варианта ЮП-460 делят одну кучу сырья).
- Хелперы: [`ui-helpers.ts`](ui-helpers.ts) — seed через `/settings/dev`, approve,
  take-to-work, чтение журнала передач; [`api-helpers.ts`](api-helpers.ts) — бесфайловый сетап.
- **Строку адресуем по `data-row-key="<position_id>"`**, а не поиском по видимому
  `#<id>`. Колонка `id` скрывается набором колонок, поэтому текстовый локатор
  переставал находить строку ровно тогда, когда её статус менялся, — и падал
  уже после того, как продукт отработал верно. Атрибут стоит и на строках
  доски передач, и на строках «Контроля выполнения»
  ([`ExecutionRow.tsx`](../src/features/execution/components/ExecutionRow.tsx)).
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
`npm --prefix frontend run test:e2e:ui` (широкий @ui: полный цикл ЮП-009,
импорт, одна строка плана — вместе с smoke-шлюзом, который он подтягивает) и
`npm --prefix frontend run test:e2e:smoke e2e/transfers-auto-accept.spec.ts`
(передача: Send → auto-accept → in_progress). Это минимально достаточный
уровень уверенности для флоу, который операторы используют ежедневно.

## Владение dev-стеком

Стеком владеет **Playwright** (`webServer` в [`playwright.config.ts`](../playwright.config.ts)):
он сам стартует backend и frontend, сам ждёт готовности (`/api/health` и `/`),
сам показывает их вывод и по завершении прогона убивает своё дерево процессов.
БД готовится до прогона: `npm run e2e:prep` в [`package.json`](../package.json)
(`db:up` → `db:wait` → `db:migrate`) — `webServer` поднимает команды
параллельно, а `npm run backend` сам Docker не поднимает.

Отдельный запуск стек не требует. Ручной стек нужен только для отладки, и
тогда запускать прогон надо с явным флагом владения:

```bash
# терминал 1 — стек поднят руками
npm run dev

# терминал 2 — прогон идёт против него и НЕ трогает его
PW_REUSE_STACK=1 npm --prefix frontend run test:e2e:ui
```

Без `PW_REUSE_STACK=1` прогон при занятых 8012/5172 **падает** с сообщением
Playwright про занятый порт и чужой стек не трогает. Молча брать чужой стек
нельзя: он может быть старше рабочего дерева, и E2E поедет против старого
бэкенда — это уже случалось (E2E шли с новым контрактом сортировки против
бэкенда со старым, `500` на `/api/stock/import/remainders/preview`).

Прогон без флагов:

```bash
npm --prefix frontend run test:e2e:ui
npm --prefix frontend run test:e2e:smoke
npm --prefix frontend run test:e2e:playwright-ui   # Playwright UI mode (отладка)
npm --prefix frontend run test:e2e:report
```

## Уборка после прогона

Стек убирает Playwright — тело процесса, которое его подняло, на Windows
вместе с reloader'ом uvicorn. Раньше стек поднимал `global-setup.ts` через
`spawn(..., { detached: true, shell: true })` и сразу отпускал, а teardown
угадывал, чей это процесс, по регуляркам; с `uvicorn --reload` угадывание
промахивалось и оставляло `python scripts/dev_server.py`, державший :8012
в LISTENING с мёртвым воркером. Следующий прогон видел занятый порт и падал
на «Тест-стек недоступен» — то есть уборка предыдущего прогона ломала
следующий.

Осталось у [`global-teardown.ts`](global-teardown.ts) (в конфиге как
`globalTeardown`) только то, что Playwright за собой не убирает: осиротевшие
`chrome`/`headless_shell`/`ffmpeg` от прерванного прогона. Порты он не трогает
принципиально — при `PW_REUSE_STACK=1` чужой стек должен пережить прогон.
Teardown не бросает исключений (иначе замаскировал бы падение теста), всё
убитое пишет в stdout с префиксом `[e2e:teardown]`.

Проверка идемпотентности (три прогона подряд, без ручного kill):

```bash
npm run dev:ports                        # :8012/:5172 свободны
npm --prefix frontend run test:e2e:smoke # PASS
npm run dev:ports                        # снова свободны
npm --prefix frontend run test:e2e:smoke # PASS
npm run dev:ports                        # снова свободны
```

Прогон, сорванный убийством самого процесса Playwright, стек убрать не
успевает: тогда `npm run dev:kill`.

## Кеш «уже проходил на этой версии»

[`pass-cache.ts`](pass-cache.ts) запоминает результат каждого теста по ключу
«версия кода + проект + путь заголовка». Версия — **коммит вместе с диффом
рабочего дерева** (`git rev-parse HEAD` + `git status` + `git diff HEAD`):
одного хеша коммита мало, незакоммиченные правки кеш переживать не должен.
Файл — `frontend/.playwright/e2e-passed.json` (в `.gitignore`).

```bash
E2E_SKIP_PASSED=1 npm --prefix frontend run test:e2e:ui
```

Что делает флаг: тест, который на этой версии уже проходил, пропускается
(`skipped` с причиной), прогон гоняет непроверенное и упавшее. Падение
вычищает запись — следующий прогон обязан его гонять. Без флага прогон всегда
полный; в CI флаг не включается: там нужен полный результат, а не «зелёное
минус кеш».

Пропуск сделан **автофикстурой** в [`fixtures.ts`](fixtures.ts), а не
`test.beforeEach`/`test.afterEach` из общего модуля: Playwright выполняет хуки
в области файла, который их зарегистрировал, и при переиспользовании воркера
между спеками такие хуки отваливаются после первой спеки (проверено: 1 запись
кеша на 6 тестов).

Записи переживают несколько worker-процессов: перед записью файл
перечитывается, по каждому ключу побеждает более свежая запись — иначе
перезапись от соседнего воркера откатывала бы результаты.

## Переменные окружения

| Переменная | По умолчанию | Назначение |
|------------|--------------|------------|
| `PLAYWRIGHT_TEST_BASE_URL` | `http://localhost:5172` | UI (baseURL в config) |
| `E2E_API_URL` | — | Только для `@smoke`; fallback в `api-helpers.ts`: `http://localhost:8012` |
| `PW_REUSE_STACK` | — | `1` — стек поднят руками, Playwright его не трогает и не поднимает свой |
| `E2E_SKIP_PASSED` | — | `1` — пропускать тесты, уже прошедшие на этой версии кода |

```cmd
set E2E_API_URL=http://localhost:8012/api
set PLAYWRIGHT_TEST_BASE_URL=http://localhost:5172
set PW_REUSE_STACK=1
set E2E_SKIP_PASSED=1
```

## Конфигурация

[`playwright.config.ts`](../playwright.config.ts):
- `testDir: ./e2e`
- `workers: 1`, `fullyParallel: false`
- Проекты (порядок и fail-fast — через `dependencies`): `smoke`
  (`grep: /@smoke/`) → `ui-e2e` (`grep: /@ui/`, `grepInvert: /@ui-narrow/`,
  зависит от `smoke`) → `ui-narrow` (`grep: /@ui-narrow/`, зависит от `ui-e2e`)
- `retries: 2` в CI
- `webServer`: `npm --prefix .. run backend` (`/api/health`) и `npm run dev`
  (`/`), `reuseExistingServer: false` — свой стек, чужой не берём

## Фикстуры

[`fixtures.ts`](fixtures.ts):
- `authenticatedPage`, `loginAsAdmin`
- `seedTestData` — legacy; в `@ui` используйте `seedReferenceDataViaUI`
- `_passCache` — автофикстура кеша «уже проходил на этой версии» (флаг
  `E2E_SKIP_PASSED=1`), см. [`pass-cache.ts`](pass-cache.ts)

## Существующие спеки

| Файл | Тег | Сценарий | Статус |
|------|-----|----------|--------|
| `full-cycle.spec.ts` | `@ui` | Полный цикл ЮП-009: каталог и остатки — живой импорт через UI-визарды, план — сетап API (без xlsx) → approve → запуск → маршрут → отгрузка | ✅ канон |
| `route-workflow.spec.ts` | `@ui` | Реальный импорт главного «Упаковочного плана» (xlsx через UI-визард) + инфо о маршруте в таблице плана | ✅ |
| `single-line-cycle.spec.ts` | `@ui` | Одна строка плана (ЮП-009, сетап API) → approve → запуск → цикл «передачи ↔ участки»: цепочка адресатов читается из журнала передач (включая складские секции), задача завершается на текущем участке, до «Отправлено» | ✅ |
| `approve-freshness.spec.ts` | `@ui` | Свежесть: позиция, утверждённая на плане (одиночно и массово), видна на «Контроле выполнения» после перехода кликом по сайдбару — без F5. Навигация только кликами и без ввода в поиск: и то и другое пересоздаёт или обходит кэш и затыкает баг | ✅ регресс |
| `sawing-multi-length-split.spec.ts` | `@ui-narrow` | Пила: распил одной задачи на несколько разных длин (2,7 м → 0,9 м + 1,8 м) порциями через доску; ledger + остатки по длинам. Сетап — API (план без xlsx), в кадре только действие участка | ✅ |
| `sawing-four-lengths-cycle.spec.ts` | `@ui-narrow` | Пила в полном цикле (ЮП-2083): каталог/остатки (2,75 м)/план из 4 позиций (ГП-раскрой 2,7 м → 0,9 + 1,35 + 1,8 + 2,7, П/ф 2,7, ГП одиночный 1,35, ГП без резки) — сетап API (без xlsx) → approve → запуск → маршрут с двумя порциями на пиле → отгрузка. Дальше только UI | ✅ |
| `yup460-shared-raw-pile.spec.ts` | `@ui-narrow` | ЮП-460: окно / гребенка / без пресса делят одну кучу сырья; план из 3 строк — сетап API (без xlsx) | ✅ |
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