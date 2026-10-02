# T-303 — мёртвые `selectin`-связи не грузятся

## Главное: одна из четырёх связей оказалась не мёртвой

Инвентаризация объявила четыре связи без потребителей. Три мёртвые, одна нет:

**`User.sections` — живая связь.** Её читает свойство

```python
# app/models/user.py
@property
def section_ids(self) -> list[int]:
    return [s.id for s in self.sections]
```

а `section_ids` отдают `UserOut` и `MeResponse` через `from_attributes`. То есть
grep по `user.sections` нашёл только записи в `users.py` и не дошёл до свойства.

Это обнаружилось **тестом, а не чтением кода**: с `lazy="raise"` на связи упали
**27 тестов** — `test_users.py` и `test_me_ttl.py`, все с одной причиной
`Error extracting attribute: InvalidRequestError: 'User.sections' is not
available due to lazy='raise'` по полю `section_ids`. Связь возвращена в
`selectin`, и теперь это зафиксировано тестом
`test_user_sections_stays_eager_because_section_ids_reads_it`, чтобы следующая
инвентаризация не объявила её мёртвой третий раз.

Отдельно: моя проба (`t303_probe_lazy.py`), которая переключала `rel.lazy` в
рантайме, показала «всё ОК» во всех режимах — **это была ложь**. Стратегия
связи выбирается на этапе конфигурации маппера, и подмена атрибута уже
настроенной связи ничего не меняет. Проба пришлось выбросить;authority —
только прогон тестов.

## Что изменено

| Связь | Было | Стало | Почему |
|---|---|---|---|
| `ProductionRoute.rules` | `selectin` | `raise` | потребителей нет: `routes.py:190` берёт правила отдельным `select(RouteMatchingRule).where(route_id=…)` |
| `RouteRuleProfile.rules` | `selectin` | `raise` | потребителей нет: `load_selection_rules_for_profile` идёт прямо `WHERE profile_id IN (…)` |
| `StorageProductionGroup.sections` | `selectin` | `raise` | потребителей ноль |
| `User.sections` | `selectin` | **`selectin`** | **живая связь** — читается через `section_ids` |

`raise` выбран, а не удаление: чтение без явной подгрузки должно **падать
громко**, а не превращаться в скрытый запрос. Это тот же приём, что срез D
применил к `get_sections_summary`.

`ProductionRoute.stages` и `RouteStage.operations` **не тронуты** — они читаются
(`routes.py:159, 230` и `production_planning.py:612`).

## Замер (dev-данные, только SELECT, rollback, «до» через stash на той же БД)

| Ручка | SQL до | SQL после | дельта |
|---|---|---|---|
| `GET /routes` | 4 | **3** | −1 |
| `GET /routes?include_steps` | 9 | **8** | −1 |
| `GET /routes/{id}` | 9 | **8** | −1 |
| `GET /route-selection-rules` | 8 | **7** | −1 |
| `GET /route-rule-profiles` | 3 | **2** | −1 |

Ровно минус один запрос на ручку — снятая связь была одна на ручку.

## Честно: две из трёх снятых связей на этих ручках не проявились

Замер показывает **−1**, а не −3, и это стоит объяснить, а не списать:

- `ProductionRoute.rules` на `/routes*` и `RouteRuleProfile.rules` на
  `/route-selection-rules` — снялись, это и есть минус один.
- `User.sections` и `StorageProductionGroup.sections` в профиле **остались**.
  Они срабатывают не сами по себе, а **вслед за материализацией `Section`**:
  `Section.users` грузит `User` (а тот тянет свои связи), `Section.spg_links`
  грузит `StorageProductionGroup` (и тот тоже). А сами `Section.users` /
  `Section.spg_links` — это selectin-связи, которые в этой серии уже признаны
  ненужными (инвентаризация: ни одна из трёх связей `Section` не нужна ни одной
  из семи ручек), но `Section` в `routes.py` материализуется как ORM-объект.

То есть убирать дальше имеет смысл **не связи, а материализацию `Section`** в
`routes.py` — теми же колонками, как в `overview` и в справочниках маршрутов.
Это отдельная работа, и в этом тикете я её не делал.

## Тесты

`backend/tests/test_dead_selectin_303.py`:

- параметризованная проверка, что три мёртвые связи не `selectin`;
- `test_user_sections_stays_eager_because_section_ids_reads_it` — фиксирует,
  что `User.sections` остаётся `selectin` и что причина в свойстве
  `section_ids`;
- `test_materializing_route_does_not_load_its_rules` — счётчик SQL: материализация
  `ProductionRoute` стоит ровно два запроса (маршрут + его `stages`), третьего
  (правила) быть не должно.

Запись `user.sections` здесь **не** дублируется: её покрывают существующие
`test_users.py` и `test_me_ttl.py` — именно они показали поломку. Мои первые
версии этих тестов падали с `MissingGreenlet` на собственной фикстуре, то есть
добавляли хрупкость поверх уже работающего покрытия; я их убрал, а не
подгонял.

## Проверки

- `npm run test:pytest` (PYTEST_NUM_WORKERS=2) — зелёный;
- `ruff check backend` — зелёный;
- миграций нет.

## Границы

- `app/transfers/**` — срез A, не трогал.
- `app/services/shopfloor/queries_sections.py` — срез D, не трогал.
- Сиды: проверял чтения связей, увидел, что `SECTIONS_DATA`/`SECTION_OPS` — это
  константы, а не ORM-чтения, поэтому на переход `lazy` они не влияют; глубже
  не копал.
- Логика ручек не менялась, только стратегия загрузки.

## Откат

Revert коммита. Все три связи возвращаются в `selectin` одной правкой.
