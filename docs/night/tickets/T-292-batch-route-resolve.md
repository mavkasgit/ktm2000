# T-292 — батч-резолв маршрутов и продуктов

**Тикет:** #292 · **Ветка:** `night/2026-10-02-a` · **Режим:** wide refactor, expand
**Блокирует:** #296, #297, #298 (перевод вызывающих на батч-форму).

## Проблема

`resolve_position_route` (`backend/app/services/route_matcher.py:229`) вызывается
почти всеми списками позиций в цикле. Стоимость вызова — от 1 SQL (сохранённый
`route_id`) до 7–12 SQL (динамическая пересборка маршрута, подбор по правилам,
сверка сигнатуры). Кэш результата `make_position_route_cache_key` (L204) включает
весь `source_payload`, поэтому на реальных данных ключ уникален почти на каждую
позицию и кэш не бьётся.

Второй раздатчик — `_resolve_effective_product_ids`: без кэша между позициями,
а `resolve_pair_by_component_skus` (`product_pair_resolver.py:124`) читает
`SELECT *` по `product_pairs` и `products` на каждый вызов.

## Что сделано (expand, ни один вызывающий не переведён)

1. **Новый модуль `backend/app/services/position_route_batch.py`:**
   * `PositionRouteBatchCache` — снимок справочников на список позиций:
     маршруты (одним `SELECT`, ими же служат сохранённые назначения и поиск по
     коду/имени из ADR-0051), профили, продукты, батчи импорта,
     `RouteSelectionBatchCache` и `RouteBuildBatchCache` по одному на профиль,
     фактические сигнатуры кандидатов (этапы пачкой).
   * `load_position_route_batch_cache()` — наполнение снимка; число запросов не
     зависит от числа позиций.
   * `position_route_identity_key()` — **нормализованная идентичность** позиции.
   * `resolve_position_routes_batch()` — резолв списка с мемоизацией по ключу.
2. **`route_matcher.py`:** `resolve_position_route` получил необязательный
   keyword-only параметр `batch`. Без него поведение прежнее; ни один вызывающий
   не переведён. Резолв не переписывался — батч-форма вызывает тот же код.
3. **`product_pair_resolver.py`:** `PairResolutionCache` (кэш на один
   HTTP-запрос) + необязательный `cache=` у `resolve_pair_by_component_skus` и
   `resolve_effective_product_ids`; ключи — `pair_component_key` и
   `effective_product_ids_key`. Отрицательный ответ кэшируется тоже.
4. **`production_planning_rows.py`:** у обёртки `_resolve_effective_product_ids`
   появился необязательный `cache=` — хук для волны 2, без изменения поведения.

## Ключ идентичности: почему такой

Ключ — это то, что резолв **реально читает**, а не сырой payload:

| ветка | что читает payload | что входит в ключ |
|---|---|---|
| ручное подтверждение / сохранённое назначение | ничего | payload **не входит** |
| динамическая пересборка | через мемоизированную сборку | `(built.name, built.signature, built.error)` |
| подбор по правилам | целиком (условия адресуют любые поля и сырые колонки Excel) | полный payload |

На ветке пересборки узкий ключ корректен, потому что `BuiltRoute`
мемоизируется по derived-входу в `RouteBuildBatchCache.built_routes`: один и тот же
`BuiltRoute` — те же имя, сигнатура и вердикт сборки, а дальше резолв смотрит
только на них и на строки маршрутов снимка. Звужать ключ до полей payload было бы
некорректно — условия правил читают произвольные пути, и такая «нормализация»
подменила бы маршрут у другой позиции.

## Замер (dev-данные, под нагрузкой; БД владельца, только SELECT + rollback)

Вызывающий: `production_planning_rows._build_planning_rows_for_positions`
(GET `/production-planning/rows`), 91 позиция.


| вариант | SQL | сумма по БД, мс | wall, мс |
|---|---|---|---|
| ДО (как сейчас) | 1907 | 2141.7 | 3381.6 |
| ПОСЛЕ (батч-резолв + кэш пар) | 198 | 253.4 | 486.1 |

Ответ **идентичен**: `json.dumps(rows_before, sort_keys=True) ==
json.dumps(rows_after, sort_keys=True)` → `True`, 91/91 строк.
Файлы: `docs/night/logs/measure_292.py`, `measure_292_result.json`.

**Контракт разделяемого результата.** Позиции одной идентичности получают
один и тот же объект `ResolvedRouteInfo` (по аналогии с разделяемыми
строками `RouteSelectionBatchCache`): его читают, не мутируют. Волне 2,
если вызывающему нужна своя копия, — `dataclasses.replace`.

Разбивка по раздатчикам (тот же набор позиций):

| раздатчик | SQL до | SQL после | расхождений ответов |
|---|---|---|---|
| маршруты | 1729 | 20 | 0 |
| продукты (`resolve_effective_product_ids`) | 0 | 0 | 0 |

**Ложный кандидат на этих данных.** Все 91 позиция dev-базы имеют
`product_id`, поэтому `_resolve_effective_product_ids` отдаёт `[product_id]`
без единого запроса — N+1 по парам на dev-данных **не воспроизводится** (в
справочнике 5 `product_pairs`, но ни одна позиция в него не заходит). Выигрыш от
`PairResolutionCache` на этом наборе равен нулю и может проявиться только на
данных с парными позициями без снапшота. Кэш оставлен: он ничего не ухудшает
(без него — те же 2 запроса, с ним — 2 запроса на запрос и 0 на позицию), но
пользу его на этих данных подтвердить нельзя.

## Сравнение вариантов

| вариант | SQL на список | почему не основной |
|---|---|---|
| **A. Batch-prefetch (снимок) — выбран** | O(1): 20 на 91 позицию | снимает оба раздатчика разом и снимает SQL с ветки пересборки, где кэш по позиции бессилен |
| B. Per-request кэш результата резолва | O(число различных payload) | кэш `make_position_route_cache_key` уже есть и не бьёт именно из-за полного payload; сужение ключа без снимка не снимает 1729 запросов |
| C. Нормализованный identity map | O(число различных идентичностей) | сам по себе SQL не убирает: без снимка каждая промахнутая идентичность всё равно стоит 7–12 запросов |

Выбран A, а B и C встроены в него как слой мемоизации: A убирает SQL, B/C
убирают повторный резолв на позициях с одинаковой идентичностью.

## Границы: что НЕ трогали

* `production_planning.py` и `production_plans.py` — их правят #296/#297/#298.
* Ни один вызывающий `resolve_position_route` не переведён (чистый expand).
* Миграций нет: снимок читает существующие таблицы.
* `position_remainders.py:184` имеет свой частичный мемо пар по
  `pair_component_key`; он не трогался (чужой файл волны 2) — там кэш пар
  можно заменить на `PairResolutionCache` отдельным шагом.
* `make_position_route_cache_key` оставлен как есть: он публичный контракт для
  существующих вызывающих (`route_validation`, `plan_validation`,
  `production_planning_rows`). Новая форма использует другой ключ.

## Критерии (числом)

* `resolve_position_routes_batch` == последовательные `resolve_position_route`
  на списке из всех ветвей (тест `test_batch_matches_per_row_on_all_branches`).
* Конфликт сигнатуры и fallback по имени без кода сохранены
  (`test_batch_keeps_signature_conflict_and_legacy_name_fallback`).
* Подбор по правилам: маршрут, причина, required/excluded, диагностика —
  те же (`test_batch_selection_branch_keeps_reasons_and_diagnostics`).
* 40 позиций → ≤ 6 SQL (`test_batch_sql_count_does_not_grow_with_positions`).
* Повторная позиция в одном запросе → 0 SQL, включая нерезолвящуюся пару
  (`test_pair_cache_serves_repeat_without_sql`,
  `test_pair_cache_remembers_unresolved_pair`).
* Полный `npm run test:pytest` зелёный, `ruff check backend` зелёный.

## Откат

Всё расширяющее: удалить `position_route_batch.py`, убрать необязательные
параметры `batch`/`cache` из `route_matcher.py`, `product_pair_resolver.py`,
`production_planning_rows.py` и тест `tests/test_position_route_batch_292.py`.
Ни один существующий вызывающий после отката ведёт себя иначе.

## Как подключает волна 2

Маршруты — вместо цикла `resolve_position_route` по позициям:

```python
from app.services.position_route_batch import (
    load_position_route_batch_cache,
    resolve_position_routes_batch,
)

cache = await load_position_route_batch_cache(db, positions)   # 1 раз на запрос
route_info_by_id = await resolve_position_routes_batch(db, positions, cache=cache)
```

Продукты — один кэш на запрос, во все вызовы списка:

```python
from app.services.product_pair_resolver import PairResolutionCache

pair_cache = PairResolutionCache()
await product_pair_resolver.resolve_effective_product_ids(db, pos, cache=pair_cache)
# в production_planning_rows обёртка уже принимает cache=
```

Метрика подключения — число SQL на один вызов списка (сейчас 1729 на 91
позицию, должно стать ≤ 20 + константа вызывающего).
