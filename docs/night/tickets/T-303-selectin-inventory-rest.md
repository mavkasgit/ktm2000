# T-303 — инвентаризация остальных связей `lazy="selectin"`

Продолжение инвентаризации: в первом отчёте (`T-303-inventory.md`) проверены были
связи `Section`. Здесь — остальные девять из модели.

**Метод тот же и с той же оговоркой:** профиль показывает, что *исполнилось*,
поэтому «связи нет в профиле» не означает «связь не нужна», а «связь есть в
профиле» не означает «связь нужна». Поэтому по каждой связи сначала читается
**код потребителей**, и только потом снимается число запросов.

## Связи и их потребители (по коду)

| Связь | Кто читает | Вердикт |
|---|---|---|
| `ProductionRoute.stages` | `routes.py:159, 230` (`/routes`, `/routes/{id}`) | **нужна** там, где читается |
| `RouteStage.operations` | `production_planning.py:612, 1950+`, `routes.py` | **нужна** |
| `RouteMatchingRule.conditions` | `plan_import_service.py:172, 442` | **нужна** (путь импорта) |
| `User.sections` | только **записи** в `users.py:172, 174, 191, 280, 283, 288`; чтений нет | **мёртвый вес** |
| `StorageProductionGroup.sections` | **ноль** потребителей | **мёртвый вес** |
| `RouteRuleProfile.rules` | **ноль** чтений; `load_selection_rules_for_profile` идёт напрямую `WHERE profile_id`, а не через профиль | **мёртвый вес** |
| `ProductionRoute.rules` | **ноль** чтений; `routes.py:190` берёт правила отдельным `select(RouteMatchingRule).where(route_id=…)` | **мёртвый вес** |
| `RouteSelectionRule`-связи профиля | см. выше | — |

Итог: **4 из 9 связей не читаются нигде** в `backend/app` вне моделей.

## Почему мёртвые связи всё равно стоят денег

`lazy="selectin"` срабатывает на каждый materialизованный экземпляр. Поэтому:

- `User.sections` — не «про ручки пользователей». Он срабатывает там, где
  материализуется `User`, а `User` грузится из `Section.users`. То есть он
  приходит **вторым порядком** вслед за связью `Section`.
- `StorageProductionGroup.sections` — то же вслед за `Section.spg_links`.
- `ProductionRoute.rules` и `RouteRuleProfile.rules` — вслед за материализацией
  `ProductionRoute` и `RouteRuleProfile`.

Это видно в профиле: `/routes/{id}` тянет `User.sections` и
`StorageProductionGroup.sections`, хотя ни один из его обработчиков не имеет
дела до пользователей или складских групп.

## Замеры (dev-данные, только SELECT, rollback)

| Ручка | Всего SQL | Из них selectin | Состав |
|---|---|---|---|
| `GET /routes` | 4 | 3 | `stages` ×1, `RouteStage.operations` ×1, `rules` ×1 |
| `GET /routes?include_steps` | 9 | 6 | + `User.sections` ×1, `spg.sections` ×1, `rules` ×2 |
| `GET /routes/{id}` | 9 | 6 | то же |
| `GET /route-selection-rules` | 8 | 4 | `RouteRuleProfile.rules` ×2, `User.sections` ×1, `spg.sections` ×1 |
| `GET /route-rule-profiles` | 3 | 1 | `RouteRuleProfile.rules` ×1 |

Обращаю внимание на `GET /routes`: **3 из 4 запросов** — это eagerly-связи, и
все три из них (`.rules`, а `.stages`/`.operations` — как минимум в части
`.rules`) попадают в мёртвые или непрофильные. Список маршрутов — дешёвая
ручка, а стоит она как четыре запроса вместо одного.

Ни одна из этих ручек не имеет N+1: все числа константны. Поэтому речь не об
ускорении «на страницу», а об убирании постоянной нагрузки на каждый тик.

## Что предлагаю

Ничего не правил — это инвентаризация. Кандидаты на отдельные правки, по
убыванию выгоды:

1. **`User.sections` и `StorageProductionGroup.sections`** — убрать `lazy="selectin"`
   (или заменить на `lazy="raise"`), если ни один путь не читает их. Осторожно:
   `User.sections` пишется в `users.py`, и там присваивание списка секций при
   `lazy="raise"` не сломается, а вот `user.sections = []` на пустом объекте
   потребует проверки. Выигрыш — 2 запроса на любой ручке, где материализуется
   `Section` или `User`.
2. **`ProductionRoute.rules` и `RouteRuleProfile.rules`** — то же. `rules.py`
   уже читает правила отдельным запросом, так что eager-связь не нужна нигде.
   Выигрыш — 1 запрос на `/routes` и 1–2 на `/route-selection-rules`.
3. `RouteStage.operations` и `ProductionRoute.stages` — **не трогать**, они
   читаются.

## Границы

- `app/transfers/**` — срез A. Не проверял и не трогал.
- `app/services/shopfloor/queries_sections.py` — срез D.
- Сиды — не трогал: часть чтений может быть только там, это отдельная проверка.
- Кода не менял: `git diff --stat` по `backend/` пуст.
