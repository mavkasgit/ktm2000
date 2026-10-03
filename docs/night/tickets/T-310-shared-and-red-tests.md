# T-310 — журнал действий в общий стиль таблиц

Тикет: https://github.com/mavkasgit/ktm2000/issues/310
Ветка: `night/2026-10-03-c`, worktree `C:/Users/LogoPrint/VibeCoding/ktm2000-night-c`
База: `99b9902`; слияния `main`: `c5f15bd` (срез A, `922b52c`) и `1945f83`.

Тикет выполнен **в два прохода**. Первый — shared-правки и red-каркас теста
(содержательная часть страницы тогда пересекалась с зоной среза A по шапке).
Второй — сама страница, после слияния A. Итог: каркас зелёный, полный
прогон без падений.

## Что сделано

### 1. Shared: тон `ok` в `frontend/src/shared/lib/rowTones.ts`

Добавлен в `RowTone` и во все пять словарей (`ROW_TONE_WASH`, `ROW_TONE_STRIPE`,
`ROW_TONE_TEXT`, `ROW_TONE_CARD`, `ROW_TONE_GROUP_RAIL`):

| словарь | значение |
|---|---|
| `WASH.ok` | `bg-emerald-50/20 hover:!bg-emerald-50/40` |
| `STRIPE.ok` | `border-l-4 border-l-emerald-400` |
| `TEXT.ok` | `text-slate-900 dark:text-slate-100` |
| `CARD.ok` | `border border-emerald-200 bg-emerald-50/20 text-slate-900 rounded-lg border-l-4 border-l-emerald-400` |
| `GROUP_RAIL.ok` | `border-l-4 border-l-emerald-400` |

Ключевое отличие от `completed` — тот же эмеральд, но **без `line-through` и
без `opacity-60`**: у `completed` зачёркивание значит «дело закрыто и неактуально»
(передача, завершённое задание), а успешная запись журнала — живое
подтверждение. Отличие зафиксировано комментарием над типом, чтобы следующий
правящий не «унифицировал» `ok` обратно в `completed`.

Существующие тоны не тронуты: `git diff` по файлу — **13 вставок, 1 удаление**
(удалена строка объявления типа, заменена на неё же с добавленным `"ok"`).

### 2. Shared: зелёный `ToggleTone` в `frontend/src/shared/ui/FiltersPanel.tsx`

`ToggleTone` пополнился значением `"emerald"`, в `TOGGLE_TONE_CLASS` добавлена
запись в том же виде, что у соседних тонов (checked — заливка 600, unchecked —
подложка 50 + текст 700, бейдж счётчика белым по appropriate-фону). Типы
полей, дефолт `tone ?? "neutral"` и рендер `renderToggleField` не менялись.

### 3. Red-каркас `frontend/src/features/sections/pages/AuditLogsPage.test.tsx`

Новый файл, 5 тестов, написан **до** правки страницы. Мок `@/shared/api/auditLogs`
по образцу `ActionsJournalPage.test.tsx` (тот же приём: `importOriginal` +
подмена одного экспорта, `QueryClient` с `retry: false`).

Покрытие по AC тикета (п. 8):

| тест | что проверяет |
|---|---|
| рендерит строки журнала тонами по статусу и статусом-Badge | тон `success → ok` / `error → scrap` / `info` без тона, высота строки 32px у всех трёх, статус подписью («Успешно»/«Ошибка»/«Информация») |
| фильтр статуса уезжает в параметры запроса | клик «Ошибки» ⇒ `getAuditLogs({status: "error"})`; клик «Все записи» ⇒ `status: undefined` |
| пустой журнал без единой записи | текст «История событий пуста.» **внутри `<td>`**, и второго текста нет |
| пустой результат фильтра при непустом журнале | текст «Нет записей, соответствующих заданным фильтрам и поисковому запросу.» **внутри `<td>`**, и «История событий пуста.» нет |
| детальная строка раскрывается и сворачивается | клик по строке ⇒ `audit-detail-row-1` с заголовком «Детали события» и полным сообщением; повторный клик убирает |

Зафиксированный контракт, который держит этот файл (его и вводит правка
страницы): `audit-row-{id}`, `audit-detail-row-{id}`,
`filter-status-{all|success|error|info}`, оба текста пустого состояния.

Проверки «внутри `<td>`» — не про разметку ради разметки: поплавок пустого
состояния над таблицей убирает шапку колонок, а колонки в журнале задаются
описанием `auditColumns`, и без единой строки таблица схлопывалась бы целиком.

Классы проверяются **через сам словарь** (`ROW_TONE_WASH.ok`,
`TABLE_ROW_DENSE.rowHeightPx`), а не литералами: тест проверяет, что страница
взяла тон из общего словаря, и переживёт правку значений внутри словаря.

## Доказательство

### Red-каркас действительно красный, и по содержательной причине

```
npx --prefix frontend vitest run src/features/sections/pages/AuditLogsPage.test.tsx \
  --root frontend --coverage.enabled=false
→ Test Files  1 failed (1)
  Tests       5 failed (5)
```

Причины падения (verbose-репортер), по одной на тест:

| тест | причина |
|---|---|
| тоны + Badge | `Unable to find an element by: [data-testid="audit-row-1"]` |
| фильтр статуса | `Unable to find an element by: [data-testid="audit-row-1"]` |
| пусто «История событий пуста.» | `expected null to be truthy` (текст найден, `closest("td")` — `null`) |
| пусто «Нет записей…» | `expected null to be truthy` (то же) |
| раскрытие строки | `Unable to find an element by: [data-testid="audit-row-1"]` |

То есть красный не из-за опечатки в импорте: обе пустые проверки **нашли свой
текст** и упали на `closest("td")` — мок, рендер и запрос отработали, не
хватает ровно того, что даёт правка страницы. Остальные три упали на
отсутствующих `data-testid` строк.

### Shared-правки зелёные

```
cd frontend && npx tsc -p tsconfig.json --noEmit        → 0 ошибок (exit 0)

npx vitest run src/shared/ui/FiltersPanel.test.tsx src/features/sections/lib/taskView.test.ts
→ Test Files  2 passed (2)
  Tests       13 passed (13)
```

`taskView.test.ts` гонялся не формально: `TaskTone = Exclude<RowTone, "scrap">`
— расширение `RowTone` меняет этот тип, и доска участков берёт из него и заливку,
и полосу, и карточку. Тесты тона доски зелёные.

### Полный прогон после первого прохода (каркас красный — так и задумано)

Состояние на тот момент; итоговое число — в разделе «Второй проход».

```
npm --prefix frontend run test
→ Test Files  1 failed | 156 passed | 1 skipped (158)
  Tests       5 failed | 1291 passed | 1 skipped (1297)
  Duration    66.14s
```

Единственный упавший файл — `src/features/sections/pages/AuditLogsPage.test.tsx`
(этот же каркас, 5 тестов). Все 156 остальных файлов зелёные: 1291 passed,
1 skipped. Раздельно прогнанные `FiltersPanel.test.tsx` + `taskView.test.ts` —
13 passed (см. выше).

Состояние прогона ожидаемое: каркас написан до правки страницы и держит её
красной. Число тестов не уменьшилось — оно выросло на 5 относительно базовых
1292 (1291 passed + 1 skipped) добавленными кейсами.

## Второй проход: правка `AuditLogsPage.tsx`

Коммит `250444a`. Срез A слит (`c5f15bd`), шапку не трогал — её добавил он.

### Правки прода по AC

| AC | что сделано |
|---|---|
| 1 | Раскладка `page-header` → `FiltersPanel` → `DATA_TABLE_STYLES.container`; карточка `bg-white rounded-xl shadow-sm border` убрана |
| 2 | Панель — `FiltersPanel`: `search` → `custom` с `DateRangePicker` → четыре `toggle` со счётчиками из `counts`, общий `onReset`; «Сбросить период», печать и bulk убраны |
| 3 | Тон `ok` и зелёный `ToggleTone` — см. первый проход |
| 4 | Шапка `cn(DATA_TABLE_STYLES.headerRow, DATA_TABLE_STYLES.headerCell, TABLE_ROW_DENSE.headerCell)` |
| 5 | Строки `style={{height: TABLE_ROW_DENSE.rowHeightPx}}`, `TABLE_ROW_STYLES.defaultRow`, ячейки `TABLE_ROW_DENSE.cell`, `font-medium` снят; статус — `Badge` (`TABLE_ROW_DENSE.badge`), кружок-иконка 28px убран; тона `success → ok`, `error → scrap`, `info → plain`, полоса `ROW_TONE_STRIPE` на первой ячейке |
| 6 | Загрузка и пусто — строки `tbody` с `colSpan`; оба текста сохранены дословно |
| 7 | Детальная строка — `colSpan`, авто-высота, `bg-muted/30`; основная строка осталась 32px |

Полоса тона лежит на **первой ячейке**, а не на `<tr>`: таблица объявлена
`border-separate`, границы строк в ней не рисуются — на `<tr>` полоса была бы
не видна (то же наблюдение зафиксировано в `TaskView.tsx`).

Заливка строки, подпись бейджа и тон вынесены в один словарь
`STATUS_PRESENTATION`: раньше это были три независимых тернарника в разметке,
и подпись статуса жила ещё и отдельно в `auditColumns` для попапера фильтра.

`data-testid`: `audit-row-{id}` и `audit-detail-row-{id}` на строках. У тумблеров
`filter-status-*` в каркасе **не вводились** — у поля `FiltersPanel` нет
testid, и ради одного экрана расширять общий контракт панели незачем; тумблеры
находятся по подписи кнопки (`getByRole("button", { name: /^Ошибки/ })`).

### Финальные прогоны

```
cd frontend && npx tsc -p tsconfig.json --noEmit   → 0 ошибок (exit 0)

vitest AuditLogsPage.test.tsx
  → Test Files  1 passed (1)
    Tests       5 passed (5)          ← было 5 failed на старой раскладке

npm --prefix frontend run test
  → Test Files  157 passed | 1 skipped (158)
    Tests       1297 passed | 1 skipped (1298)
    Duration    57.58s

cd backend && ruff check .           → All checks passed!
```

Эталон в `main` — 1291 passed / 1 skipped / 0 failed. Стало 1297 passed:
прибавились 5 кейсов каркаса и один новый файл `run-lock.test.ts`, пришедший из
`main` слиянием. Падений нет, число зелёных не уменьшилось.

### Правка подтверждена разбором отрендеренного DOM

Не «по коду видно» — вывод отрендеренной разметки:

* карточки-обёртки в DOM нет: `container.innerHTML.includes("rounded-xl")` → `false`;
* `class="p-3"` в DOM остался ровно один — от самой `FiltersPanel` (`rounded-lg border bg-card/60 p-3`), в файле страницы `p-3` не встречается вовсе;
* строка успеха: `<tr data-testid="audit-row-1" style="height: 32px;" class="bg-emerald-50/20 hover:!bg-emerald-50/40 hover:bg-accent/60 …">` — тон `ok` и 32px в разметке;
* ячейка статуса: `px-2 py-1 border-l-4 border-l-emerald-400` + `Badge` с текстом «Успешно»;
* пустое состояние: `<tbody><tr><td colspan="9" class="px-2 py-10 text-center">…История событий пуста.</td></tr></tbody>` — внутри таблицы, а не поплавком;
* детальная строка: `<tr data-testid="audit-detail-row-1" class="bg-muted/30"><td colspan="9" …>`.

Разбор был разовым (черновик-скрипт) и удалён; в набор тестов не попал.

## Что НЕ делалось

- `backend/app/api/routes/audit_logs.py` и `features/sections/lib/auditColumns.ts` — по тикету готовы, не трогались;
- печать и массовые операции в панели — по AC их нет (выбирать нечего);
- e2e-спека на аудит — по плану §3.1 не плодится;
- правки навигации журнала (`Layout.tsx`, `JournalTabs`, меню) — зона среза A.

## Откат

`git revert 250444a` — страница и правка каркаса. Shared-правки откатываются
`git revert 0845a86`, каркас как новый файл — `git revert 0f02c58`.