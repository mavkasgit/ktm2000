# T-303 — инвентаризация загрузок `Section` и прочих `lazy="selectin"`

**Шаг 1 из двух: только измерение, кода не менял.** Правки — по сигналу оркестратора,
и только в местах, не занятых другими срезами.

Методика та же, что в #290/#297/#298: прямой вызов ручки в транзакции с `rollback`,
счёт SQL — engine-слушатель `before_cursor_execute`/`after_cursor_execute`, dev-данные
`:5440/ktm2000_prod` только на чтение. Меркалка `docs/night/logs/t303_inventory.py`,
вывод `t303_inventory.txt`.

Место вызова снимается по цепочке `greenlet.parent`: sync-движок SQLAlchemy
исполняется в отдельном greenlet, поэтому обычный `traceback` показывает только
sqlalchemy — пришлось подниматься к кадрам async-обработчика вручную.

## Связи с `lazy="selectin"` в моделях

| Связь | Файл |
|---|---|
| `Section.users` | `app/models/section.py:48` |
| `Section.operations` | `app/models/section.py:49` |
| `Section.spg_links` | `app/models/section.py:50` |
| `ProductionRoute.stages` | `app/models/route.py:55` |
| `ProductionRoute.rules` | `app/models/route.py:56` |
| `RouteStage.operations` | `app/models/route.py:112` |
| `RouteMatchingRule.conditions` | `app/models/route.py:198` |
| `RouteRuleProfile.rules` | `app/models/route.py:245` |
| `StorageProductionGroup.sections` | `app/models/spg.py:51` |
| `User.sections` | `app/models/user.py:81` |

**Важная методическая оговорка.** `selectin` срабатывает **один раз на коллекцию**,
а не на объект: если загрузить 33 `RouteStage` одним запросом, `operations`
придёт одним запросом. Поэтому в инвентаризации нельзя считать «N+1» всё, что
похоже на связь. Явные пакетные выборки (`select(SectionOperation).where(…)`)
внешне неотличимы от selectin-формы; надёжный признак — `ORDER BY`: явные
выборки в этом коде всегда упорядочивают, selectin связи без `order_by` приходит
без него. В таблицах ниже явные выборки помечены отдельно и в N+1 **не идут**.

## Профиль по ручкам (dev-данные, section_id=10, batch 6)

| Ручка | selectin-запросов | Живой N+1 | Место |
|---|---|---|---|
| `/production-planning/rows` | 15 | нет | константа |
| `/production-planning/overview` | **83** | **ДА, ×33** | `api/routes/production_planning.py:463` |
| `/imports/{id}/positions` | 11 | нет | константа |
| `/shopfloor/sections/{id}/board` | 4 | нет | константа |
| `/shopfloor/sections/summary` | 4 | нет | константа |
| `/transfers/ready` | 8 | нет | константа |
| `/shopfloor/sections/{id}/board/column-values` | 0 | — | чисто, ORM-объектов нет |

Кроме #297/#298/#296 (слиты), живых N+1 в списке остался **один**.

## Что ответу реально нужно, а что нет

Главный результат: почти все `Section`-связи в этих ручках **не нужны ответу**,
а тянутся потому, что ORM-объект `Section` материализуется целиком.

### 1. `overview:463` — единственный живой N+1 (33×) — МОЖНО править

```python
for pos in positions:
    route_id = position_route_map[pos.id][0]
    if route_id is not None:
        if route_id not in route_stages_cache:
            stages = (await db.execute(
                select(RouteStage).where(RouteStage.route_id == route_id) …))
```

Кэш используется **только** для `stage.section_id` — строки 473 и 588
(`if stage.section_id == section.id`). Ни `stage.operations`, ни `stage.sequence`
не читаются нигде.

Но ORM-объект `RouteStage` тянет за собой две цепочки: `operations` (selectin)
и `ProductionRoute.stages` (selectin через backref). На 33 маршрутах это
33 × (1 + stages + operations) ≈ **99 запросов вместо одного**.

**Нужно:** колонки `(route_id, section_id)`. **Не нужно:** `operations`,
`ProductionRoute.stages`, `sequence`. Файл мой, границы соблюдены.

### 2. `overview:480` — `select(Section)` ради четырёх колонок — МОЖНО править

`SectionOut` (`production_planning.py:164`) = `section_id`, `section_code`,
`section_name`, `section_type`. **Все три связи не нужны.** Замена на выборку
колонок: 4 запроса → 1. Файл мой.

### 3. `summary:829` — `select(Section)` ради семи колонок — ГРАНИЦА НЕ ВЕРНА

Ответ читает `id`, `code`, `name`, `type`, `sort_order`, `icon`, `icon_color`.
**Все три связи не нужны.** 4 запроса → 1.

**Но:** оркестратор отнёс summary к `shopfloor/queries.py` как к моей зоне.
На деле `queries.py` — это 32-строчный ре-экспорт, а реализация
`get_sections_summary` живёт в `app/services/shopfloor/queries_sections.py:743`
(и `get_section_board` там же, `:206`) — то есть в файле среза D. **Границу надо
переиграть**, иначе summary и board не попадут ни в чьи руки.

### 4. `board:241,262` — `select(RouteStage)` ради `route_id`/`section_id` — ГРАНИЦА НЕ ВЕРНА

`all_stages` используется только как `s.route_id` и `s.section_id`. Операции
ручка грузит **явно** строкой ниже (`select(SectionOperation).order_by(…)`),
так что `RouteStage.operations`-selectin там инцидентный. Тот же
`queries_sections.py` — срез D.

### 5. `board:305` — это **явная** пакетная выборка, не selectin

В N+1 не идёт и исправления не требует. Отмечено, чтобы при правке доски её
не списали в «остаток связей».

### 6. `transfers/ready:1239,1273` — связи **нужны**, не трогать

Ручка реально читает `src_stage.operations` и `dst_stage.operations`
(строки операций в ответе), а из `Section` — `id` и `name`. То есть
`RouteStage.operations` здесь оправдан; неоправданны разве что
`Section.users` и `Section.spg_links`. Но файл `app/transfers/` — зона среза A,
и по AC «№2 не трогать `app/transfers/**`» я его не трогаю. **Занесено сюда как
находка для них.**

### 7. `rows:851` и `imports:583` — остаток из #296

По 4 запроса в каждой: общий `select(Section)` целиком в
`app/services/route_builder.py:144` и `app/services/route_selection.py:551`
(1 + 3 связи). Ответу эти ручки не нужны **ничего** из связей `Section`.
Файлы общие, правка задевает потребителей — это и есть предмет #303.

## Сводка по «нужно / не нужно»

| Место | Грузится | Ответу нужно | Лишнее |
|---|---|---|---|
| `overview:463` | `RouteStage` ×33 | `section_id` | `operations`, `ProductionRoute.stages` |
| `overview:480` | `Section` ×1 | 4 колонки | все 3 связи |
| `summary:829` | `Section` ×1 | 7 колонок | все 3 связи |
| `board:241,262` | `RouteStage` | `route_id`, `section_id` | `operations` |
| `ready:1239,1273` | `Section`, `RouteStage` | `name`, `operations` | `Section.users`, `Section.spg_links` |
| `route_builder:144`, `route_selection:551` | `Section` (все) | зависит от потребителя | зависит от потребителя |

**Ни одна из трёх связей `Section` не нужна ни одной из семи ручек**, кроме
одной оговорки: `/transfers/ready` нуждается в `RouteStage.operations`, но не в
`Section.users`/`Section.spg_links`. То есть `Section.users` и `Section.spg_links`
не нужны **нигде** в этом списке.

## Что предлагаю на шаг 2

В границах «можно» (`production_planning_rows.py`, `imports.py`, справочники):

1. `overview:463` — колонки `(route_id, section_id)` вместо ORM `RouteStage`
   (убирает ~99 запросов, единственный живой N+1 в списке).
2. `overview:480` — колонки вместо ORM `Section` (4 → 1).

Вне моих границ, но нужно решение оркестратора:

3. `summary:829` и `board:241,262` — то же самое, но файл у среза D.
4. `route_builder.py:144` / `route_selection.py:551` — предмет самого #303.
5. `app/transfers/queries.py` — находка для среза A.

## Границы (что НЕ трогал)

- `app/transfers/**` — срез A.
- `app/services/shopfloor/queries_sections.py` — срез D.
- `app/services/route_builder.py`, `route_selection.py` — общий код, предмет
  шага 2 по отдельному сигналу.
- Миграций нет, моделей не менял, тесты не запускал (кода не трогал).
