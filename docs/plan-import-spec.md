# Спека: ускорение и стабилизация импорта плана

Источник решений: карта [Wayfinder #157](https://github.com/mavkasgit/ktm2000/issues/157),
тикеты #158 (профиль), #159 (стабильность), #160 (стратегия), #161 (прототип), #162 (замер).
Артефакты: `research/plan-import-profile` (`docs/research/plan-import-profile.md`),
`prototype/import-preview-ux` (`frontend/prototype/import-preview.prototype.html`).

## 1. Базисы

- Эталон: `Упаковочный план.xlsx` (53 КБ, 322 строки листа / 289 parsed / 5 парных).
- Замер #162 (изолированная БД, сид 56 SKU): парсинг ~22 мс / 0 SQL;
  create без профиля 643 SQL / 821 мс; create с `rule_profile_id` 11 993 SQL / 10 690 мс
  (~41.5 SQL/строку, 92% времени — `build_route_from_profile` без межстрочного кэша);
  apply 588 SQL / ~690 мс (~289 flush + `db.get` без кэшей); ответ 1.73–2.07 МБ.
- Приоритет: стабильность → скорость. Лимиты строк/МБ не вводить. Фона (job+polling) нет.
  Маппинг колонок шаблонов не ломать. Глоссарий — `CONTEXT.md` («размеры», не «габариты»).

## 2. Цели (ориентиры, калибруются повторным прогоном скрипта #162)

- create без профиля ≤ 1.5 с; create с профилем ≤ 3 с; apply ≤ 1 с (на эталоне).
- Ответ `POST /imports/excel` ≤ 300 КБ (без `after_data` целиком).
- Повторный прогон скрипта-замера — обязательная приёмка каждого тикета ниже.

## 3. Каталог кодов строк (фиксирован, #159 Q1)

Статус строки — `plan_import_service.py:1145`: есть errors → `invalid`,
иначе warnings → `warning`, иначе `pending`.
Новый код — только с явной классификацией error/warning в этом списке.

Errors (блокируют, `invalid`): `product_not_found`, `product_inactive`,
`product_pair_not_found`, `hanger_calc_zero`, `no_route_candidate` / `selection.error`,
`active_route_has_no_steps`, `route_contains_inactive_section`,
`duplicate_sku_due_date`, сырьевой `raw_error` (`raw_length_not_found` и т.п.).

Warnings (не блокируют): `raw_length_substituted`, `paired_hanger_adjusted`,
`hanger_quantity_not_set`, `input_dimensions_unresolved`, `product_name_missing`,
`invalid_input_length` / `invalid_output_length`, `paired_row_auto_included:*`,
`row_selection_applied:*` / `row_selection_auto_included:*`,
`paired_profile_product_unmapped`.

## 4. Изменения pipeline

### 4.1. Подбор маршрута — межстрочный кэш (ядро, ~1200–2000 SQL → единицы)
- `select_route_for_payload` (`route_selection.py:226`): вынести из построчного цикла
  загрузку правил профиля, таблицы активных маршрутов, join этапов, `_section_id_by_code`,
  `_sections_by_id` — кэш по `profile_id` на время батча. `select_route_cache` оставить как есть.
- Кэш `build_route_from_profile` по сигнатуре маршрута (`plan_import_service.py:974-1064`):
  сейчас 0/289 попаданий, пересборка на каждую строку. Ключ — хэш входа сборки.
- Кэш `pair_length_candidates_mm` в `resolve_pair_n` (сегодня перезапрос на пару мимо `pair_n_cache`).
- Семантика подбора не меняется; только чтение, один коммит в конце как раньше.

### 4.2. Apply — bulk (ядро, ~289 flush → 1)
- `apply_change_set` (`production_plan_service.py:95-219`): один flush в конце вместо
  `flush()` на позицию (`:168`, `:215`); закэшировать `db.get(Product)`
  (`plan_validation.py:63`) и `db.get(ProductionRoute)` (`route_matcher.py:213`) по id.
- Отчётность сохраняется и расширяется: `extra` = created/updated/ignored/cancelled/
  skipped_invalid/**duplicates** (дубли сегодня уходят в голый `continue`, `:110-112`).
  Те же счётчики — в сообщение аудита `Импорт плана (применен)`.
- Построчных savepoint'ов нет: частичность закрыта `skip_invalid`/кодами (§3).
  Дефолтов не менять: UI всегда шлёт явный `skipInvalid` (две кнопки диалога).

### 4.3. Ответ create — лёгкие строки (вместо пагинации; пагинация отклонена)
- `POST /imports/excel` → 201:
  `summary { total, valid, warning, invalid, duplicates, errors: {код: n} }` (считает сервер),
  `items[]` — лёгкие строки `{ item_id, source_row_numbers, source_sku, quantity, status, change_action, codes[] }`,
  без `after_data` целиком.
- `GET /imports/batches/{id}/items?cursor=…` — постраничное дочитывание лёгких строк (для больших файлов).
- `GET /imports/items/{item_id}?full=1` — полный `after_data` одной строки (раскрытие в диффе).
- Фронт (`ImportWizard`, дифф): диалог работает от `summary`; таблица — все лёгкие строки сразу,
  детали по клику. Отдельный тикет — chip «Дубли» в диалог (`applyStats`) и таблица.
- Объём цели: ≤ 300 КБ на эталоне.

### 4.4. Удаление батча — 409 + выбор (§5 контракта #159 Q3)
- `DELETE /production-plans/{p}/batches/{b}`: при живых downstream-данных —
  `409 { code: batch_has_released_positions | downstream_transfers_exist,
  blockers: [{position_id, reason: released | transfer №…}], safe_action: delete_drafts_only, drafts: n }`.
  Закрывает дыру: сегодня rollback-`ValueError` глотается (`production_plans.py:295-298`),
  каскад сносит задачи/передачи.
- UI: экран блокировки — ЧТО мешает (список), ПОСЛЕДСТВИЯ вариантов, ВЫБОР:
  «Отмена» / «Удалить только черновики (n)» (позиции `released`, задачи, передачи не тронуты) /
  «Удалить всё» — disabled с объяснением запрета.
- Прототип экрана: вариант B (`prototype/import-preview-ux`, `?variant=b`).

## 5. Приёмка (каждый тикет)

1. Повторный прогон скрипта-замера #162 на эталоне (create ±профиль, apply, вес ответа).
2. `Transfer ↔ StockTransaction integrity`: `assert_no_invariants_violations` в затронутых тестах.
3. Существующие тесты импорта зелёные (`test_plan_position_dimensions.py:332` — реимпорт → `ignore_unchanged`).
4. Поведение на эталоне глазами оператора: диалог (A), 409-экран (B) — по прототипу.

## 6. Вне скоупа спеки

- Редизайн страницы планирования; импорт остатков; лимиты; фоновый импорт
  (вернуться, только если синхронный путь не уложится в §2);
  пересмотр индексов `ix_plan_positions_import_hash/row` (отдельный вопрос при регрессе записи).
