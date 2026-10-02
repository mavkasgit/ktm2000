# T-292b — резолв пар в остатках через `PairResolutionCache`

**Тикет:** #292 (побочная находка, закрыта оркестратором отдельно) · **Ветка:** `night/2026-10-02-a`

## Проблема

`position_remainders.committed_demand_by_product_ids` разбирал парные позиции
(`product_id IS NULL`) своим локальным мемо:

```python
resolved_cache: dict[tuple[str, ...], list[int]] = {}
resolved_key = pair_component_key(paired_component_skus(position))
if resolved_key not in resolved_cache:
    resolved_cache[resolved_key] = await resolve_effective_product_ids(db, position)
```

Мемо шёл по SKU компонентов, но сам резолв каждый раз читал справочник заново:
`SELECT *` по `product_pairs` + `SELECT` по `products`. Для повторов одной пары
это и правда отсекалось, но для **разных** пар справочник перечитывался целиком
на каждой — 2 запроса на пару.

Второй дефект того же мема: ключ строился только по SKU компонентов, поэтому
позиция **со снапшотом** пары (`source_payload.product_pair.resolved`) и позиция
**без снапшота** с теми же SKU делили одну запись кэша и получали ответ друг
друга. Ключ из #292 (`effective_product_ids_key`) различает эти три входа явно.

## Что сделано

`committed_demand_by_product_ids` больше не имеет своего мемо — резолв идёт
через `PairResolutionCache` из #292:

```python
pair_cache = product_pair_resolver.PairResolutionCache()
for position in pair_positions:
    component_ids = await product_pair_resolver.resolve_effective_product_ids(
        db, position, cache=pair_cache
    )
```

Семантика не менялась: тот же резолв, тот же fallback на `SectionPlanLine` для
нерезолвящихся пар, та же сумма спроса. Правка — 3 строки в одном файле.

## Доказательство

**Тест на число SQL (дискриминирующий).** `test_pair_demand_sql_does_not_grow_with_distinct_pairs`
замеряет число SQL при одной запущенной паре и при трёх **разных** парах.
На старом коде тест падает:

```
AssertionError: три разные пары дали 9 SQL против 5 у одной
```

На новом — проходит: число запросов не зависит от числа разных пар (справочник
читается один раз, индекс строится целиком).

**Тест на семантику.** `test_pair_position_commits_demand_to_both_components`:
две запущенные позиции пары дают спрос **обоим** компонентам (600.0 на каждый) —
развёртка пары работает, а не только один компонент из строк плана. Такой тест
в файле не было: парные позиции остатками не покрывались вообще.

## Замер (dev-данные, под нагрузкой; БД владельца, только SELECT + rollback)

`committed_demand_by_product_ids` на 222 артикулах, `docs/night/logs/measure_292b.py`:

| вариант | SQL | строк спроса | сумма спроса | спрос совпал |
|---|---|---|---|---|
| ДО | 2 | 65 | 43750.0 | — |
| ПОСЛЕ | 2 | 65 | 43750.0 | `True` (побайтово) |

**Разница на dev-данных нулевая, и это ожидаемо:** в базе владельца нет ни одной
парной позиции (`product_id IS NULL` — 0 из 91), поэтому `pair_positions` пуст и
цикл резолва не выполняется ни разу. Выигрыш проявляется только на данных с
запущенными парными позициями; его величина измерена тестом выше (2 запроса на
пару → 2 запроса на запрос).

## Границы («что НЕ трогали»)

* `pair_positions` остались теми же позициями — смена отбора означала бы правку
  семантики спроса, а не резолва.
* Fallback на `SectionPlanLine` для нерезолвящихся пар не кэшируется: он
  привязан к `position.id` и на разных парах разный. Это отдельный кандидат,
  в объём не входил.
* `production_plans.py` / `production_planning.py` не трогались.

## Откат

Вернуть 8 строк локального мема в `committed_demand_by_product_ids` (git revert
одного коммита). Поведение идентично, разница — только в числе запросов.

## Ссылки на логи

`docs/night/logs/measure_292b.py`, `measure_292b_before.json`,
`measure_292b_after.json` (каталог в `.gitignore`).
