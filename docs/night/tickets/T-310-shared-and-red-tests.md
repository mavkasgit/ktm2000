# T-310 (подготовительный блок) — shared-тон `ok`, зелёный `ToggleTone`, red-каркас `AuditLogsPage.test.tsx`

Тикет: https://github.com/mavkasgit/ktm2000/issues/310
Ветка: `night/2026-10-03-c`, worktree `C:/Users/LogoPrint/VibeCoding/ktm2000-night-c`
База: `99b9902`.

Это **первый из двух проходов** по #310. Содержательная часть (строки, ячейки,
`Badge`, панель фильтров в `AuditLogsPage.tsx`) намеренно не сделана: она
пересекается с зоной среза A по шапке/заголовку того же файла и идёт после
слияния A. Тикет **не закрыт**.

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

### Полный прогон фронта

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

## Что НЕ сделано (заблокировано слиянием среза A)

Не тронуто в `AuditLogsPage.tsx` **ничего** — ни шапки (зона A), ни тела:

- карточка-обёртка `bg-white rounded-xl shadow-sm border` (AC 1);
- панель на `FiltersPanel` с четырьмя toggle и `onReset` (AC 2);
- шапка `DATA_TABLE_STYLES.headerRow/headerCell + TABLE_ROW_DENSE.headerCell` (AC 4);
- строки 32px, `TABLE_ROW_DENSE.cell`, `TABLE_ROW_STYLES.defaultRow`, тона
  `ok`/`scrap`/`plain` по статусу, `Badge` вместо кружка-иконки (AC 5);
- пусто/загрузка внутрь `tbody` `colSpan`-строкой (AC 6);
- фон детальной строки `bg-muted/30` (AC 7);
- введение `data-testid` `audit-row-{id}` / `audit-detail-row-{id}` /
  `filter-status-*`, без которых каркас остаётся красным.

`backend/app/api/routes/audit_logs.py` и `features/sections/lib/auditColumns.ts`
не читались на предмет правок — они готовы по тикету.

## Следующий шаг

После `git merge main` (в `main` к этому моменту сольётся срез A) — довести
`AuditLogsPage.tsx` по AC 1–7 так, чтобы 5 тестов каркаса стали зелёными.

## Откат

`git revert <sha>` — два коммита: shared-правки (аддитивны, откатываются
чисто) и тестовый файл (новый файл, откатывается удалением).