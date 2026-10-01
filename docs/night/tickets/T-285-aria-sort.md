# T-285 — aria-sort на th и подписи сортировки (#285)

- **Категория:** продуктовый код (frontend), доступность шапки таблиц
- **Статус:** DONE — коммит `debfd22`
- **Дата:** 2026-10-01/02, смена B
- **Связь:** выделено из #204; ADR-0037

## Проблема и доказательство

`aria-sort` ставила **одна** таблица — контроль выполнения, и то пропом
`getAriaSort` из `ExecutionPage` с локальной формулой (4 строки), плюс
inline-дубликат в `ExecutionTable.header.test.tsx`. На остальных таблицах
состояние сортировки скринридеру не сообщалось вовсе, а «навигация по
заголовкам столбцов» — основной способ понять таблицу — молчала.

## Что сделано

1. `frontend/src/shared/lib/multiSort.ts` — общий `getAriaSort(currentSorts, field)`
   рядом с `nextMultiSortConfigs`; `none` — «сортируема, порядок не выбран».
2. `aria-sort` на каждом сортируемом `<th>`: 15 мест рендера —
   `ExecutionTable`, `HrmsEmployeesTable`, `ProductWipStatsDialog`,
   `ExecutionEventsTable`, `ExecutionStagesTable`, `PlanPage`,
   `HangerCalcTable`, `RawMaterialsPage`, `SectionTasksBoard`, `AuditLogsPage`,
   `SettingsBackupsPage`, `ImportRemaindersDialog`,
   `StockTransactionsHistoryDrawer`, `TransfersPage` (ready + журнал, два
   `<TableHead>`), `StockBalancesPanel`.
   Условие то же, что у кнопки сортировки: `column.sortField ? … : undefined`,
   поэтому атрибут есть ровно у сортируемых колонок.
3. `ExecutionTable`: проп `getAriaSort` удалён, таблица считает значение сама из
   `sortConfigs` общим хелпером; `ExecutionPage` больше его не передаёт;
   inline-дубликат в `ExecutionTable.header.test.tsx` удалён.
4. Тесты: `multiSort.test.ts` — `none`/`ascending`/`descending` и «чужая
   колонка не влияет»; `SectionTasksBoard.sorting.test.tsx` — на живой шапке:
   сортируемая колонка `none → descending → ascending`, несортируемая
   («Операция») атрибута не имеет.
5. ADR-0037: раздел «Что не менялось» теперь описывает закрытую дыру, а не
   историческое «aria-sort на доске не появился».

## Критерии готовности (измеримые)

1. `grep -rn "getAriaSort" frontend/src` → определение в `shared/lib/multiSort.ts`
   + импорт/вызов в `ExecutionTable.tsx`; **локальных копий нет**.
2. `npx tsc --noEmit` → **0**.
3. `npx vitest run` → **1160 passed / 1 skipped** (было 1157 до новых тестов),
   падений 0.
4. `grep -c aria-sort` по 15 файлам рендера шапок → 1 в каждом (2 в
   `TransfersPage`); `DataTableColumnHeader.tsx` — 0 (он рисует содержимое, а
   не `<th>`).

## Границы: что НЕ трогали

- Значения фильтра, подписи и приоритет кнопки сортировки — это #204
  (закоммичено отдельно, `d970fbc`).
- Порядок, по которому `aria-sort` берёт состояние, — тот же `sortConfigs`,
  что подсвечивает кнопку сортировки; дефолтные сортировки экранов
  (`LOG_DEFAULT_SORT` у аудита, `backupsDefaultSortParam`) в `aria-sort` не
  отражаются — как и в состоянии кнопки. Одно правило на все таблицы.
- Ни одна таблица не переписана: добавлена одна строка в `<th>` и импорт
  хелпера.

## Откат

`git revert debfd22`. Поведение таблиц (порядок строк) не менялось — менялся
только атрибут для скринридера.

## Артефакты

- Прогоны: вывод `tsc`/`vitest` в журнале смены.
