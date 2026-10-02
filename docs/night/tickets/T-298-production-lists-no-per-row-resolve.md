# T-298 — Production-списки без построчных резолвов и per-task статусов

## Проблема

Пять эндпоинтов production-списков считали маршруты и статусы построчно.
На изолированном клоне dev-данных (900 позиций) это давало до **17 267 SQL**
на один запрос `section-totals` и **15 384** на `all-positions`.

## Методика

Как в #290/#297: прямой вызов ручки в транзакции с `rollback`, счёт SQL —
engine-слушатель `before_cursor_execute`/`after_cursor_execute`.
Меркалка `docs/night/logs/t298_measure.py`, сравнение «до/после» — `git stash`
той же правки на той же БД, то есть на идентичных данных.

**Почему не dev-данные.** На них `/all-positions` возвращает 0 строк: все 91
позиция в статусе `released`, а ручка фильтрует по статусам планирования
(`draft/invalid/valid`). Мерить там нечего. Поэтому клон раздут до 900 позиций
и статусы разведены по сценариям:

- 91 позиция `released` (с 587 задачами) — сценарий `overview` и `section-totals`;
- 809 позиций `valid` — сценарии `/all-positions` и `/{id}/all-positions`.

Разведены потому, что `overview` фильтрует по `approved|released`, а
`all-positions` — по `draft|invalid|valid`: наборы не пересекаются, оба сценария
одновременно на одном наборе статусов невозможны.

Два варианта данных, оба на том же клоне:

- **«одинаковый payload»** — раздутые позиции копируют `source_payload` образца;
- **«уникальный payload»** — в `source_payload` каждой позиции дописан её `id`.

Второй вариант — честный: ключ кэша `make_position_route_cache_key` включает
`source_payload`, поэтому у реальных позиций из разных строк Excel он почти
всегда уникален, и локальная мемоизация в цикле не помогает.

## Замеры

### Вариант «уникальный payload» (реалистичный)

| Эндпоинт | SQL до | SQL после | дельта | wall-мс до | wall-мс после |
|---|---|---|---|---|---|
| `/production-planning/overview` | 2723 | **99** | −96% | 5280.5 | 695.0 |
| `/production-plans` | 3 | **2** | −33% | 33.7 | 20.4 |
| `/production-plans/{id}/all-positions` | 15384 | **32** | **−99.8%** | 38349.3 | 452.9 |
| `/production-plans/all-positions` limit=500 | 9513 | **32** | **−99.7%** | 16806.3 | 384.0 |
| `/production-plans/{id}/section-totals` | 17267 | **187** | **−98.9%** | 39602.8 | 687.5 |

### Вариант «одинаковый payload»

| Эндпоинт | SQL до | SQL после |
|---|---|---|
| `overview` | 2723 | 99 |
| `/production-plans` | 3 | 2 |
| `/{id}/all-positions` | 32 | 32 |
| `/all-positions` limit=500 | 32 | 32 |
| `section-totals` | 1915 | 187 |

Разница между вариантами — **весь эффект на `all-positions`**: при одинаковом
payload локальный кэш по `make_position_route_cache_key` и так схлопывал 809
резолвов в несколько, и правка ничего не добавляла. Стоит сказать прямо: на
синтетике с одинаковым payload ручка уже не была N+1.

## Ответы не изменились

SHA-256 полного JSON ответа, до и после. Совпадение **побайтовое во всех пяти
эндпоинтах, в обоих вариантах данных**:

| Эндпоинт | digest до | digest после |
|---|---|---|
| `overview` | `b754e3ae0e8d1f5f` | `b754e3ae0e8d1f5f` |
| `/production-plans` | `b19957f46f712a88` | `b19957f46f712a88` |
| `/{id}/all-positions` (одинаковый payload) | `a5f09dcbafe38b4a` | `a5f09dcbafe38b4a` |
| `/{id}/all-positions` (уникальный) | `92aff5548bda9bf9` | `92aff5548bda9bf9` |
| `/all-positions` limit=500 (одинаковый) | `c8a2e04914b76b90` | `c8a2e04914b76b90` |
| `/all-positions` limit=500 (уникальный) | `2767f8a12e226baa` | `2767f8a12e226baa` |
| `section-totals` | `1f2041b7c721f282` | `1f2041b7c721f282` |

## Что сделано

### 1. `overview` — 2723 → 99

`production_planning.py`:

- Внутри цикла `sections × positions × lines × tasks` звался scalar
  `pm.get_task_cache(db, wt.id)` — **3 SQL на задачу** (921 запрос из 2723 на
  307 задачах). Поднят выше цикла: `pm.get_tasks_cache_bulk(db, [wt.id …])`, один
  вызов существующего метода из `stock/services.py`.
- Там же `db.get(RouteStage, wt.route_stage_id)` + ленивый `stage.operations` —
  поднято в один запрос `select(RouteStage).options(selectinload(RouteStage.operations)).where(id.in_(…))`.
- `resolve_position_route` в цикле по позициям → `resolve_position_routes_batch`
  (контракт #292).

Задача, отсутствующая в батче, поднимает `RuntimeError`, а не подставляет ноль:
молчаливый ноль — это другое значение, чем «неизвестно».

### 2. Три цикла резолва маршрутов → батч

`production_plans.py`: `resolve_position_routes_batch(db, positions)` вместо
цикла с локальным кэшем в `all_positions`, `all_plan_positions` и `section_totals`.

### 3. `/production-plans` — 3 → 2

`list_plans` делал на каждый план два скана (сводка по статусам + общий count).
Теперь один `GROUP BY production_plan_id, status` на все планы; `total` —
сумма по статусам. Отдельный `count` не нужен: у плана без позиций и с нулём
позиций ответ одинаковый (ноль).

### 4. Кэш пар в `_compute_position_stock_figures`

`_resolve_effective_product_ids` звался на каждую позицию без кэша; добаавлен
`PairResolutionCache` на вызов (контракт #292).

## Границы (что НЕ трогал)

- SQL-пагинацию production (пункт AC «`/all-locations`-семантику не трогать»):
  `all_plan_positions` по-прежнему делает `count` + `LIMIT/OFFSET` на стороне БД.
- Одиночные `resolve_position_route` в `route-check`, `section-totals`-смежных
  одиночных обработчиках (`production_plans.py:962`, `:2375`) — там одна позиция,
  N+1 нет.
- Формы выборок, фильтры, сортировка, набор полей ответа — без изменений.
- Кэш `route_stages_cache` в `section_totals` (хороший образец из тикета) оставлен
  как был.

## Проверки

- `npm run test:pytest` (PYTEST_NUM_WORKERS=2) — зелёный, ≥2022;
- `ruff check backend` — зелёный;
- миграций нет.

## Откат

Revert коммита. Правки локальны в двух модулях роутов.
