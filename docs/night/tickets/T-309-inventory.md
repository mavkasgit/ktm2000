# T-309 — Инвентаризация перед правкой #309

Срез B, ночь 2026-10-03. Статус: **подготовка завершена, продуктовый код не тронут**.
Правки `ActionsJournalPage.tsx` не начаты — файл в зоне среза A.

## 1. Блокировка

`frontend/src/features/reversal/pages/ActionsJournalPage.tsx` переписывает срез A
(шапка + навигация). Файл входит в зону B, поэтому до его мержа срез B в него
не заходит. Ниже — всё, что нужно, чтобы начать сразу после мержа.

## 2. «До» — числа прогона

Прогон в worktree `ktm2000-night-b` на `99b9902`, до единой правки.

| Прогон | Команда | Результат |
|--------|---------|-----------|
| Юниты, весь фронт | `npm --prefix frontend run test` | Test Files **156 passed \| 1 skipped** (157), Tests **1291 passed \| 1 skipped** (1292), 100.29 s |
| Юниты, срез reversal | `npx vitest run src/features/reversal` (в `frontend`) | Test Files **5 passed** (5), Tests **28 passed** (28), 19.12 s |
| Типы | `npx tsc -p tsconfig.json --noEmit` (в `frontend`) | 0 ошибок (exit 0), 26.93 s |

Разбивка reversal: `PreviewZones` 5, `JournalRowOperations` 4, `ReversePreviewDialog` 5,
`AmendDialog` 6, `ActionsJournalPage` 8 — все зелёные.

База зелёная; после правок эти числа обязаны совпасть.

## 3. Инвентаризация `JournalRowOperations.tsx`

Файл: `frontend/src/features/reversal/components/JournalRowOperations.tsx` (134 строки).

Пропсы сегодня ровно два:

| Проп | Тип | Что делает |
|------|-----|-----------|
| `action` | `JournalAction` | строка журнала; из неё берутся `id`, `action_type`, `status`, права на кнопки |
| `onChanged` | `() => void` | вызывается после успешной отмены/изменения — страница делает `invalidateAfter(queryClient, "actionReversed")` |

Что потребуется `actionColumns.ts`:

- Колонка «Операции» — служебная, без `filterField`/`sortField`. Рендерится
  `<JournalRowOperations action={action} onChanged={refresh} />`. Сам компонент в
  `actionColumns.ts` **не нужен** — только место в массиве колонок, чтобы шапка
  `map` по описанию не потеряла столбец (как `details` в `auditColumns`).
- `JournalRowOperations` править не требуется: кнопки `size="sm"` → `h-9`
  (`button.tsx:25`) плюс `py-1` ячейки (`TABLE_ROW_DENSE.cell`) дают 36+8 = 44 px
  при `rowHeightPx: 32`. **Это блокирующий момент для 32 px** — см. §7.
- Контракт, который компонент уже держит и который нельзя терять:
  `tree-button-{id}`, `reverse-button-{id}`, `amend-button-{id}`, `tree-dialog`,
  `tree-node-{id}`, текст `Цепочка действия #{id}`.
- Логика прав не трогается: `reverseByRoleForbidden` по
  `ADMIN_ONLY_REVERSE_ACTION_TYPES` + `POLICIES.rollbackImport`,
  `canReverse = status === "active"`, `canAmend = transfer_send && active`.

## 4. `DataTableColumnHeader` и сбор параметров

`frontend/src/shared/ui/DataTableColumnHeader.tsx`:

- `filterable = column.filterField !== undefined`, `sortable = column.sortField !== undefined`;
- ни того, ни другого → `<span className="text-xs font-medium text-muted-foreground">{label}</span>`
  (строка 58), т.е. колонка без сортировки рисуется голой подписью;
- иначе `SortableFilterHeader` c `field = filterField ?? sortField`.
- `exactMatch` → поиск в попапере не уезжает в запрос; `clientOnly: true` →
  `multiSelect`, значение уходит в клиентский предикат, а не в запрос.

`buildColumnApiParams` (`shared/lib/columnSpecs.ts:108`):

- перебирает `columns`, берёт только те, у кого есть `filterField`;
- значение — `readColumnValue` (выбранное значение; при `exactMatch` — только оно,
  без строки поиска);
- `toParams` → несколько параметров; `mapValue` → перекодировка, `undefined` = не отправлять;
- ключ: `column.apiParam ?? column.filterField`, значение `String(mapped)`;
- `paramKind: "number" | "boolean"` в строковом сборщике **бросает** — их собирает
  `buildTypedColumnApiParams`. Для журнала параметры строковые, значит хватает
  `buildColumnApiParams`.

`GetActionsParams` (`shared/api/actions.ts:40`) принимает ровно `page`,
`page_size`, `action_type`, `status` — ни поиска, ни сортировки.

## 5. Эталон: `auditColumns.ts` + `AuditLogsPage.tsx`

`features/sections/lib/auditColumns.ts` — образец формы:

- `export type AuditColumn = ColumnSpec<AuditFilterField> & { id; label; headerClassName? }`
  — `id`/`label` в описании колонки, не в разметке страницы;
- `const filterable = "p-0 text-left"` — общий кусок класса шапки для всех колонок;
- порядок массива = порядок в шапке и в теле;
- `mapValue: dropDash` — «—» не отправляется;
- `valueLabel` переводит серверный код в подпись оператора.

`features/sections/pages/AuditLogsPage.tsx` — образец сборки:

- `headerCellClass = ${DATA_TABLE_STYLES.headerRow} ${DATA_TABLE_STYLES.headerCell}` (строка 212);
- `<table className="w-full border-separate border-spacing-0 text-sm">` (383);
- `auditColumns.map(...)` → `<th className={headerCellClass + column.headerClassName}>`
  → `<DataTableColumnHeader column bindColumn values currentSorts onSortChange />` (386-399);
- последний `<th>` — `TableCornerResetHeader hasActiveFilters onReset dataTableHeader`
  (401-405), в теле последняя `<td>` — `TableCornerResetCell` (532);
- параметры: `buildColumnApiParams(columnFilters, columnSearchQueries, auditColumns)`
  внутри локальной функции с типом-`Pick` контракта (72-80);
- состояние — `useFilterableTable<Field>` → `bindColumn`, `columnFilters`,
  `columnSearchQueries`, `debouncedColumnSearchQueries`, `sortConfigs`,
  `handleSort`, `resetAll`, `hasActiveFilters`;
- `uniqueValues` — `useMemo` из текущей страницы строк, по одному ключу на
  фильтруемую колонку (179-198);
- `buildActiveFilterSummary` (из `@/shared/ui`) считает «Активных фильтров: N».

`frontend/AGENTS.md:85-110` фиксирует правило: семантика колонки объявляется
один раз в `ColumnSpec`; тернарник в шапке и своя `buildXColumnApiParams` с
перечислением колонок — запрещены; колонка, которую сервер не фильтрует,
объявляется **без** `filterField`/`sortField`, а не флагом.

## 6. Константы: что уже есть, чего не хватает

`shared/lib/dataTableStyles.ts`:

- `DATA_TABLE_STYLES`: `container`, `headerRow`, `headerCell`, `selectedRow` — есть;
- `TABLE_ROW_COMPACT`: `rowHeightPx: 40`, `cell`, `headerCell`, `actionButton`, `badge` — есть;
- `TABLE_ROW_DENSE`: `rowHeightPx: 32`, `cell: "px-2 py-1"`, `headerCell: "px-2 py-1"`,
  `actionButton: "h-6 px-2 text-xs"`, `badge: "px-2 py-0 text-[11px]"`, `divider` — есть.

`shared/lib/tableRowStyles.ts`: `TABLE_ROW_STYLES.defaultRow`, `selectedRow`,
`groupBlock` и прочее — есть.

`shared/lib/rowTones.ts`: `RowTone` = `waiting | activeRunning | active | completed | scrap | plain`;
`ROW_TONE_WASH`, `ROW_TONE_STRIPE`, `ROW_TONE_TEXT`, `ROW_TONE_CARD`,
`ROW_TONE_GROUP_RAIL`, функция `rowToneFill(tone)`.

Не хватает (нужно решить в реализации, не в shared):

1. **Тон журнала.** `rowTones` даёт словарь, но отображения «статус действия →
   тон» нет нигде: в reversal нет аналога `getTaskTone` из `TaskView.tsx:52`.
   Должен появиться в зоне B — `features/reversal/lib/actionColumns.ts` или
   соседний `actionTones.ts`. Заодно это естественное место для `STATUS_BADGE`,
   который сейчас живёт внутри страницы (строки 23-31).
2. **Текст тона для `reversed`.** `ROW_TONE_TEXT.completed` уже содержит
   `line-through decoration-slate-300 opacity-60` — зачёркивание из словаря,
   отдельно его объявлять не нужно.
3. **Пустое состояние.** Тексты «Загрузка…» / «Действия не найдены» держат
   `ActionsJournalPage.test.tsx:141-149`, поэтому класс
   `text-center text-sm text-muted-foreground` + один `colSpan` — как в билете.
4. **`filter-type` / `filter-status` в `FiltersPanel`.** У поля
   `kind: "select"` (`shared/ui/FiltersPanel.tsx:131-139`) **нет `data-testid`** —
   ни в типе, ни в разметке (проверено: `grep data-testid FiltersPanel.tsx` пусто).
   `shared/ui/FiltersPanel.tsx` — чужая зона. Значит два пути:
   - `kind: "custom"` с собственным `<Select data-testid="filter-type">` внутри
     `node` (пример — `TransfersPage.tsx:1323-1329`, `SectionTasksBoard.tsx:1233`);
   - оставить `kind: "select"` и снять тест через `role="combobox"`/текст.
   Первым сохраняет контракт билета «не менять селекторы» без правки чужого файла.

## 7. План `actionColumns.ts` (код не писать)

Файл: `frontend/src/features/reversal/lib/actionColumns.ts` (в зоне B, новый).

Колонки в порядке шапки:

| # | id | label | filterField | apiParam | sortField | headerClassName |
|---|----|-------|-------------|----------|-----------|-----------------|
| 1 | `id` | ID | — | — | — | `font-mono` в ячейке; ширина ~6% |
| 2 | `actionType` | Действие | `actionType` | `action_type` | — | `w-[20%]` |
| 3 | `object` | Объект | — | — | — | `w-[10%]` |
| 4 | `actor` | Инициатор | — | — | — | `w-[16%]` |
| 5 | `status` | Статус | `status` | `status` | — | `w-[12%]` |
| 6 | `createdAt` | Создано | — | — | — | `w-[16%]` |
| 7 | `operations` | Операции | — | — | — | `w-[10%] text-right` |

Решения по каждому пункту:

- **Тип поля.** `export type ActionFilterField = "actionType" | "status"`.
  Ровно две фильтруемые колонки — те, что понимает `GET /api/actions`
  (`backend/app/reversal/api.py:99-118`: `action_type`, `status`).
- **`sortField` ни у одной.** Сервер жёстко `stmt.order_by(Action.id.desc())`
  (`backend/app/reversal/api.py:124`) и параметра сортировки не принимает.
  Иконка сортировки в шапке не рисуется, `aria-sort` не ставится. Порядок
  «сначала свежие» приходит с сервера, `defaultSort` не объявляется.
- **`valueLabel`.** `actionType`: `actionJournalLabels[v] ?? v` (метка в
  `shared/lib/generated-labels.ts:422`, ключи — коды вида `transfer_send`);
  `status`: `Активно / Отменено / Изменено / Очищено`. Это же отображение
  переиспользуется в ячейке статуса и в списке значений фильтра, иначе подпись
  разойдётся с тем, что оператор видит.
- **`mapValue`.** Для `actionType` и `status` не нужен: значения совпадают с
  серверными кодами, «—» в них не бывает. Фильтр `status` выбирает одно
  значение, `clientOnly` не ставим — сервер принимает одно значение, как на
  аудите.
- **`exactMatch`.** Ставим у обеих: оператор выбирает конкретный тип/статус из
  списка, а не ищет подстроку (`DataTableColumnHeader.tsx:66-73` — при
  `exactMatch` поиск в попапере не зажигает счётчик и не уезжает в запрос).
- **Тон статусов.** Отображение в новом файле зоны B:
  `active → active` (синий, живая отменяемая), `amended → activeRunning` (янтарный,
  вмешались), `reversed → completed` (эмеральд; `line-through` приезжает из
  `ROW_TONE_TEXT.completed`), `purged → waiting` (жёлтый),
  неизвестный статус → `plain` (страница не падает — этот случай держат тесты
  `ActionsJournalPage.test.tsx:164-177`). Тон возвращает `getActionTone(status)`,
  строка — `` `${rowToneFill(tone)} ${ROW_TONE_TEXT[tone]}` `` плюс
  `style={{ height: TABLE_ROW_DENSE.rowHeightPx }}`, полоса
  `ROW_TONE_STRIPE[tone]` — на **первой ячейке**, не на `<tr>` (таблица
  `border-separate`, полоса на `<tr>` не видна — комментарий в
  `TaskView.tsx:44-47`).
- **Бейдж статуса** остаётся: тексты «Активно / Отменено / Изменено / Очищено»
  держат тесты (строки 78-81, 159-161) и e2e (строка 54). `Badge` + `TABLE_ROW_DENSE.badge`.
- **Панель `FiltersPanel`:** два поля `kind: "select"` — тип действия и статус,
  `layoutSpan` ~`min-w-[200px]`, плюс `onReset={resetAll}` и
  `hasActiveFilters={hasActiveFilters}`. Счётчик — `buildActiveFilterSummary("",
  0, { columnFilters, columnSearchQueries, columnLabels })`.
  **Поиск не добавляем** — `GET /api/actions` его не принимает, а строка,
  фильтрующая только текущую страницу, врёт оператору.
- **Сбор параметров:** один вызов
  `buildColumnApiParams(columnFilters, columnSearchQueries, actionColumns)`,
  разложенный в `GetActionsParams`:
  `action_type: params.action_type ?? null`, `status: (params.status as ActionStatus) ?? null`.
  Фильтры `data-testid` ведут в `columnFilters` через `onColumnFilterChange`
  (`useSortableColumnFilters`), поэтому состояние панели и попаперов — одно.
- **Пусто/загрузка:** одна `colSpan={8}` строка (7 колонок + угол сброса),
  класс `text-center text-sm text-muted-foreground`, тексты без изменений.
- **`TablePaginationFooter`** остаётся как есть.

### Известный конфликт, который надо решить в реализации

Высота строки: `TABLE_ROW_DENSE.rowHeightPx = 32` против трёх кнопок
`size="sm"` (`h-9` = 36 px) в `JournalRowOperations`. Соблюсти и 32 px, и
`data-testid` кнопок можно, дав кнопкам `className={TABLE_ROW_DENSE.actionButton}`
(`h-6`) — но это правка `JournalRowOperations.tsx`, файл в зоне B и менять его
можно. Альтернатива — оставить 36 px и не выставлять `rowHeightPx`; тогда AC
«строка 32 px» не выполнен. Решение принимается при реализации, здесь только
фиксирую, что оно не входит в `ActionsJournalPage.tsx` и потому не ждётmerge A.

## 8. Что осталось заблокированным

- Все правки в `ActionsJournalPage.tsx` — до мержа среза A.
- `frontend/e2e/reversal-journal.spec.ts` (чужая зона) — прогон после мержа,
  когда страница уже переписана.
- `ActionsJournalPage.test.tsx` — файл правит человек, не срез B. Селекторы
  (`action-row-{id}`, `filter-status`, `reverse-button-{id}`, `amend-button-{id}`,
  `tree-button-{id}`, тексты бейджей и «Действия не найдены») — контракт, который
  сохраняется без правок теста.

Тикет #309 не закрыт.
