# ADR-0008: Доступ сервисов к канону — carve-out «immutable snapshot»

Статус: принято. Дата: 2026-08-08. Уточняет ADR-0004 §5 (DI-правило доступа).

## Контекст

ADR-0004 §5 разрешал доступ к PlantConfig только из composition root
(Route boundary через `Depends`, явная фабрика на входе non-FastAPI
контекстов) и отклонял «module-level lazy accessor» как хрупкий при
pytest-xdist и unusable для multi-tenant. Однако на практике шесть сервисов
захватывают значения канона на import-time (`_DEFAULT_RULE = _build().…`),
а два места (`operations_defects.py`, `operations_tasks.py`) строили
PlantConfig при каждом вызове функции — runtime construction.

## Решение

Разрешить **eagerly resolved immutable snapshot** на module-level:
module-level `_DEFAULT_X = _build().…` и snapshot-константы для
leaf-функций, **если** одновременно:

1. значение — immutable snapshot канонической конфигурации;
2. не резолвится повторно при вызове функции;
3. там, где значение является параметром функции, предусмотрен explicit
   optional override для тестов/спецсценариев (для snapshot-констант
   неприменимо);
4. код не использует `build_plant_config()`/accessor как механизм получения
   текущей конфигурации в рантайме;
5. значение не используется для multi-tenant/request-scoped configuration.

Классификация паттернов:

| Паттерн | Решение |
|---|---|
| `DEFAULT = _build().x` на module level | Разрешено (carve-out) |
| `fn(x=None): x = _build().x` внутри тела функции | Запрещено |
| `fn(..., x=None)` + module-level DEFAULT fallback | Разрешено |
| `fn(..., x)` с explicit DI | Разрешено / предпочтительно где plumbing естественный |
| произвольный `build_plant_config()` в середине стека | Запрещено |

Запрет на runtime construction стал жёстче: вызов `build_plant_config()`
(в т.ч. через alias) **в теле любой функции** вне composition root —
нарушение. Два call-time места переведены на explicit DI: роут (composition
root) резолвит канон и передаёт сервису скалярные данные (`scrap_policy.*`,
карту решений); сервис не знает про канон. При отсутствии переданных данных
и наличии брака сервис отвечает fail-fast `ValueError`.

## Considered Options

- **Полный DI (обязательный параметр/конструктор на каждом уровне):**
  отклонено — plumbing через несколько уровней стека ради значений, которые
  уже можно переопределить optional override, тестируемость не растёт.
- **`arg is None → _build()` (lazy default):** отклонено — это ровно тот
  «module-level lazy accessor», который ADR-0004 §5 запретил; поведение
  начинает зависеть от момента вызова.

## Consequences

- Введён gate-тест (`tests/test_canon_access_gate.py`): AST-скан `app/` —
  `build_plant_config` внутри тела функции вне allowlist → fail. Allowlist:
  `app/main.py` (composition root FastAPI); весь `app/seeds/` исключён из
  сканирования (доступ к canon там by design — composition root сидов,
  ADR-0004 §6). Новое «свободное место» требует осознанного изменения теста.
- `operations_defects.py` / `operations_tasks.py`: `complete_task` и
  `defect_decide` получили параметры `scrap_section_type`, `scrap_code`,
  `scrap_name`, `scrap_sort_order`, а `defect_decide` — ещё и
  `defect_decision_map`; `resolve_defect_status` принимает mapping вместо
  PlantConfig.
- 6 module-level мест (`hanger_quantity.py:11`, `color_extraction.py:8`,
  `plan_validation.py:17-19`, `route_validation.py:20-23`,
  `techcards_queries.py:13`, `plan_import_service.py:50`) формально легальны
  по carve-out; каждое подлежит ревью по критериям 1-5 (тикеты #42-#47).
