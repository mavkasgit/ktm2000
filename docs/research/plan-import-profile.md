# Профиль импорта плана: где ~15 секунд (Упаковочный план.xlsx, 53 КБ)

Research-тикет: mavkasgit/ktm2000 #158 (часть карты #157).
Файл-замер: `Упаковочный план.xlsx` в корне репо (53 075 байт).
Метод: только чтение кода + лёгкие замеры без БД (тайминг чистого парсинга,
вес сериализации). Прод-код не менялся. Полный прогон через изолированную
тестовую БД не выполнялся — это следующий шаг (см. «Что мерить дальше»).

Факты о файле (замерено, `parse_factory_plan_workbook` напрямую, 3 прогона):
всего строк листа 322, распарсено 289, из них парных (`paired_profile`) 5,
строк с ошибками парсинга 0, строк с предупреждениями 6.

## End-to-end pipeline

Два HTTP-запроса:

1. `POST /imports/excel` → `create_excel_import_change_set`
   (`backend/app/services/plan_import_service.py:231`) — парсинг, запись
   батча/change-set/items, возврат `items` целиком.
2. `POST /production-plans/{id}/change-sets/{id}/apply` → `apply_change_set`
   (`backend/app/services/production_plan_service.py:54`) + `get_plan_preview`.

## Таблица этапов

| Этап | Код | Замер / оценка | Доля |
|---|---|---|---|
| Парсинг calamine (`parse_factory_plan_workbook`) | `backend/app/services/excel_import.py:116` | **~24 мс** (замерено: 25.7 / 23.0 / 23.7 мс) | ~0% |
| `_make_change_items`, цикл по 289 строкам | `plan_import_service.py:456` (цикл `:525`) | SQL-оценка ниже; единственный тяжёлый CPU — `make_hashable` рекурсивно по payload на строку, остальное — ожидание БД | доминирует (1) |
| Запись батча/items (create-путь) | `plan_import_service.py:287-367` | 5 `flush` (файл, план, батч, change-set, bulk-insert 289 items одним flush `:367`) + `log_action` + per-route flush'и при `rule_profile_id` (`:963`, `:1035`, `:1048`) | мало без профиля; растёт с числом динамических маршрутов |
| `apply_change_set`, цикл по 289 items | `production_plan_service.py:95-219` | **1 `flush` на каждую созданную/обновлённую позицию** (`:168`, `:215`) → ~289 flush'ей + ~2–3 запроса на строку | доминирует (2) |
| Сериализация ответа `items` | `_serialize_item` (`:1271`, `after_data` целиком) | **~1.4 МБ / 289 items (~4.9 КБ на item)**, `json.dumps` ~7 мс in-process (замерено на эмуляции без `route_selection`-диагностики; с `ctx_snapshot` и `candidate_routes` — 2–4 МБ). Сам dumps дёшев, дорого — передача и рендер на фронте | сотни мс, не секунды |

## SQL-счётчик на строку (статика, cache-miss)

`create_excel_import_change_set`, на каждую из 289 строк (`_make_change_items`):

- `select_route_for_payload` (`route_selection.py:226`): 1 (`load_selection_rules_for_profile`)
  + k (`_section_id_by_code` `:489` — без межстрочного кэша, по запросу на каждый
  `section_code` в actions) + 1 (`_sections_by_id` `:482`)
  + 1 (`SELECT * ProductionRoute is_active` `:389` — вся таблица маршрутов)
  + 1 (`_route_sections` join `:494` — этапы+участки всех маршрутов).
  Итого **~4+k запросов на строку**. `select_route_cache` (`:505`, `:635`)
  keyed полным payload — payload'ы строк уникальны (разные SKU/количества),
  попаданий почти нет. **При 289 строках это ~1200–2000 запросов только на подбор маршрута.**
- `RouteStage` по `route.id` (`:656`) и `db.get(Section)` (`:671`) — закэшированы
  (`route_stages_cache`, `sections_by_id_cache`), бьют только по distinct-маршрутам.
- `_load_raw_lengths_mm` (`:142`) — 1 запрос на distinct `product.id`, закэширован.
- `resolve_product_dimensions` (`dimension_validation.py:23`) — 1 запрос
  (`ProductDimension` + `selectinload`) на distinct `product.id`, закэширован
  (`typical_dimensions_cache`).
- Парные строки (здесь 5): `resolve_pair_by_component_skus`
  (`product_pair_resolver.py:87`) первым вызовом грузит **всю таблицу
  `ProductPair` + все продукты пары** (`:95`, `:100`) и матчит в Python;
  `resolve_pair_n` (`:173`) через `_pair_length_keys` (`:168`) **перезапрашивает
  `pair_length_candidates_mm` без кэша** — лишний запрос на каждую distinct-пару
  (длина × пара), мимо `pair_n_cache`.

`apply_change_set`, на каждую из 289 позиций:

- `db.get(Product)` (`plan_validation.py:63`) — **без кэша**, 1 запрос на строку.
- `resolve_position_route` (`route_matcher.py:140`): при stored `route_id` —
  `db.get(ProductionRoute)` (`:213`) на строку (кэш `route_resolve_cache` есть,
  ключ — см. `make_position_route_cache_key`); при отсутствии — `db.get(ImportBatch)`
  + `SELECT Product` + полный `select_route_for_payload` заново (`:241-249`).
- `RouteStage`/`Section` — закэшированы (`:117`, `:136`).
- **`await db.flush()` на каждую позицию** (`:168`, `:215`) — ~289 roundtrip'ов
  вместо одного bulk-flush. Плюс финальный `get_plan_preview` (`:250`, `:574`):
  1 `db.get` + 1 `SELECT` всех позиций плана.

Разовые (вне цикла): `ImportFile` select+insert, `ProductionPlan` insert,
`ImportBatch`+`ChangeSet` insert'ы, `load_selection_rules_for_profile` для снапшота,
`_load_products_by_sku` (1 запрос + 2 selectinload: `processing_flags`, `lengths`),
два `log_action`.

Грубая сводка: **~2500–3500 SQL-roundtrip'ов + ~300 flush'ей + ответ в мегабайты**.
При ~2–5 мс на roundtrip (asyncpg локально + ORM-накладные) это и есть
наблюдаемые ~8–15 с. Парсинг (~24 мс) и `json.dumps` (~7 мс) в них не входят.

## Топ-3 виновника

1. **`select_route_for_payload` на каждую строку** (`route_selection.py:226`,
   вызов `:638`): правила, вся таблица активных маршрутов и join этапов
   перечитываются сотни раз — кэш только по полному payload (`:505`, `:634`),
   общих межстрочных кэшей правил/маршрутов/секций нет. ~половина всех запросов.
2. **`apply_change_set`: flush на позицию + `db.get` без кэша**
   (`production_plan_service.py:168,215`, `plan_validation.py:63`,
   `route_matcher.py:213`): ~289 flush'ей и ~300–600 точечных чтений.
3. **Ответ `items` целиком с `after_data`** (`plan_import_service.py:384`,
   `_serialize_item` `:1271`): измерено ~1.4 МБ минимум (реально с диагностиками
   2–4 МБ) — не секунды, но главный кандидат после БД: пагинация/lazy-детали.

## Что мерить дальше (изолированная тестовая БД, скрипт-однодневка)

1. Счётчик запросов через SQLAlchemy `event.listen(Engine, "before_cursor_execute")`:
   точные цифры по этапам на сидированной БД (запуск только через
   `scripts/test-run.ps1`-лаунчер, результат удалить вместе со скриптом).
2. Wall-time сплит create vs apply на этом же файле; отдельно с `rule_profile_id`
   (динамический `build_route_from_profile` + создание маршрутов/стейджей
   с savepoint'ами `:974-1064`) и без.
3. Hit-rate `select_route_cache` / `route_stages_cache` / `sections_*_cache`
   (сколько distinct payload'ов из 289) — решает, хватит ли межстрочных кэшей.
4. Размер реального ответа `POST /imports/excel` (байты по сети) и время рендера
   `ImportDiffTable` на фронте.

Источники: `backend/app/services/excel_import.py:116-191`,
`backend/app/services/plan_import_service.py:231-389,456-525,635-662,754-784`,
`backend/app/services/route_selection.py:226-237,359-392`,
`backend/app/services/product_pair_resolver.py:87-117,144-183`,
`backend/app/services/plan_validation.py:41-63,103-145`,
`backend/app/services/route_matcher.py:140-249`,
`backend/app/services/production_plan_service.py:54-250,574-610`,
`backend/app/api/routes/imports.py:42-105`,
`backend/app/api/routes/production_plans.py:179-196`.
