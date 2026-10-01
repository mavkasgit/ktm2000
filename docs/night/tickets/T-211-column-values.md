# T-211 — справочник значений колонки в поповере фильтра

Тикет: https://github.com/mavkasgit/ktm2000/issues/211
Ветка: `night/2026-10-01`, worktree `C:/Users/LogoPrint/VibeCoding/ktm2000-night`
(база — `1ff72b1`, ночной merge в main).

## Проблема

Поповер фильтра колонки собирался из различных значений **текущей страницы**
(`uniqueValuesByField` из загруженных строк — `SectionTasksBoard.tsx` и девять
других экранов). «Нет значений» означало «в этой выборке такого значения нет»:
значение с соседней страницы в поповере не появлялось. ADR-0044 оставлял это
как известную границу и выносил серверную часть в #211.

## Срез этой ночи («эндпоинт + один экран»)

**Бэкенд** — новый эндпоинт справочника:

```
GET /api/shopfloor/sections/{section_id}/board/column-values
    ?column=product_sku
    &date_from&date_to&status&search&product_sku&dimensions&limit=50
→ { "column": "...", "values": [...], "limit": N, "truncated": bool }
```

- колонка валидируется по белому списку `BOARD_COLUMN_VALUE_FIELDS`
  (`backend/app/services/shopfloor/queries_sections.py`), чужая — **400**
  (не пустой список и не 500);
- запрос строится тем же `_build_section_board_query`, что и доска, поэтому
  справочник живёт в тех же границах (окно дат, статус, поиск, соседний
  фильтр), но **фильтр самой колонки отбрасывается** — иначе список схлопнулся
  бы к выбранному значению;
- значения — ровно то, что видно в колонке: для артикула это
  `case(source_sku like '%+%', source_sku, else_=Product.sku)` (парный профиль
  показывает «A+B»);
- `limit` + `truncated` — срез сверху, чтобы поповер не тянул весь справочник.

**Фронт** — доска участка (`SectionsTasksBoard` / `SectionsTasksPage`):
`getSectionBoardColumnValues`, ключ `queryKeys.shopfloor.boardColumnValues` под
префиксом `shopfloor-board` (инвалидация доски обновляет и справочник),
`buildBoardColumnValuesParams` + `BOARD_SERVER_VALUE_FIELDS` в
`features/sections/lib/boardQueryParams.ts`, новый проп
`filterValueOptions` у доски: серверные значения приоритетнее страничных,
`clientOnly`-колонки и их множественный выбор не менялись (ADR-0044).

## Находка: справочник отдаётся только для `product_sku`

Колонка «Размер» в белый список **сознательно не вошла**, и это не недоделка, а
разные домены значения и фильтра:

- экран показывает `taskGroupingDimensions(task)` = `input_dimensions` для
  трансформирующих задач (`groupTasksByProfile.ts:32-37`);
- фильтр доски `dimensions` сравнивает `WorkTask.dimensions`
  (`dimensions_match_clause` в `queries_sections.py:125-128`);
- значит значение из справочника по «Размеру» (вход раскроя) не сузило бы
  выборку — оператор выбрал бы значение и получил другой/пустой список.

Развести эти домены (или решить, какой из них правильный в колонке) — решение
владельца, а не ночная правка. Поэтому справочник сейчас: `product_sku`.

## Доказательства

- Доска «до»: значения берутся из строк страницы (тест
  `.../SectionTasksBoard.values.test.tsx`, второй кейс — фолбэк без справочника).
- `-- -k "column_values or section_board"` → **15 passed in 13.69s**
  (5 новых: независимость от страницы — доска отдаёт 50 из 60, справочник 60;
  игнор собственного фильтра; `limit`/`truncated`; парный «A+B»; 400 на чужую
  колонку).
- `npx vitest run` (весь фронт) — **144 passed | 1 skipped, 1173 passed | 1 skipped**;
  `npx tsc --noEmit` — чисто.
- Полный backend-прогон (`PYTEST_NUM_WORKERS=3`, под нагрузкой, параллельно
  прогон в main): **2005 passed, 3 warnings in 407.82s** (лог
  `logs/pytest-de4bba0fb952.log`).
- `ruff check backend` — All checks passed.

## Что НЕ трогали

- `frontend/src/shared/ui/SortableFilterHeader.tsx` (зона среза B/#204),
  `frontend/e2e/run-*.mjs`, `backend/app/reversal/**`,
  `backend/app/services/excel_import.py` — чужие срезы, уже в main;
- `clientOnly`-множественный выбор и `listbox`-решение гриллинга (ADR-0044);
- остальные девять экранов со страничными значениями — отдельные заходы;
- ADR-0044/0038 не переписывались.

## Остаток (не закрыто этим срезом)

- `dimensions`-колонка — ждёт решения по домену размера (см. находку);
- остальные экраны (`ExecutionPage`, `PlanPage`, `TransfersPage`, …) — по тому же
  рецепту: колонка в белый список + `filterValueOptions` на экране;
- `truncated` пока не показывается в UI (срез 200 значений с признаком);
- тикет #211 не закрывается: это вертикальный срез, не полное покрытие.

## Откат

`git revert <sha>`: эндпоинт + тесты + подключение одного экрана; схем и
миграций нет.
