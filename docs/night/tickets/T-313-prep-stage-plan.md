# T-313 — План подготовительного участка: три варианта маршрута, задания → PREP_STOCK

Тикет: [#313](https://github.com/mavkasgit/ktm2000/issues/313) · Ветка: `night/2026-10-03-313`

## Что сделано

### Сиды

| Файл | Правка |
|------|--------|
| `backend/app/seeds/import_templates.py` | новый шаблон `plan_prep_stage` («План подготовительного участка»): `sku`, `product_name`, `color`, `operation`, `quantity`, `note`. Колонки операций оставлены, лишние (Запад/Восток, вид конечного продукта, упаковка 1,8, добавить) убраны. |
| `backend/app/seeds/route_rule_profiles.py` | новый профиль `prep_stage_plan`: `route_sections = [RAW_STOCK, DRILLING, PRESSING, SHOT_BLAST, PREP_STOCK]`, `route_name_pattern = "{operations} - {shot_op}"`, `import_template_code → plan_prep_stage`. |
| `backend/app/seeds/selection_rules.py` | 7 правил профиля `prep_stage_plan`: `prep_core_sections` (route_select), `prep_drill_shot` / `prep_press_window_shot` / `prep_press_comb_shot` / `prep_shot_only` (три варианта), `prep_drill_operation` / `prep_press_operation` (resolve_operations), `prep_shot_signature` (resolve_signatures). |

Миграция Alembic не потребовалась — только сиды.

### Отклонение от чек-листа issue: ОДИН профиль вместо трёх

Issue предлагал «три профиля (по одному на вариант)» на одном шаблоне. Это не работает
в текущем рантайме, что видно чтением кода:

`backend/app/api/routes/imports.py:73-80` (`_resolve_template_context`):

```python
rule_profile_id = (
    await db.execute(
        select(RouteRuleProfile.id)
        .where(RouteRuleProfile.import_template_id == template_id)
        .order_by(desc(RouteRuleProfile.is_active), desc(RouteRuleProfile.priority), RouteRuleProfile.id.asc())
        .limit(1)
    )
).scalars().first()
```

`.limit(1)` — на шаблон выбирается **ровно один** профиль. Три профиля на одном шаблоне
означали бы, что два из них никогда не участвуют в импорте: их правила не читались бы
(`load_selection_rules_for_profile` берёт global + профиль позиции), а `route_sections`
не применялись бы.

Поэтому **один профиль** с суперсетством участков, а три варианта различает
колонка «Операция» файла через `exclude_section` в фазе `route_select` — ровно тот
механизм, который уже применяется в `packaging_map_rp` (`drill` / `press_section` /
`empty_primary`). Поведение из AC выполнено полностью: три варианта маршрута, старт
`RAW_STOCK`, финиш `PREP_STOCK`.

### Pytest

`backend/tests/test_prep_stage_plan_import.py` — 15 тестов, все зелёные:

1. **Колонки шаблона** — обязательные (`sku`/`product_name`/`quantity`), наличие
   `operation`, отсутствие колонок вне подготовительного маршрута; файл нового
   шаблона разбирает **общий** `parse_factory_plan_workbook` (свой парсер не нужен).
2. **Три ветки правил подбора маршрута** (параметризовано, 4 случая) — состав этапов
   и порядок для каждого варианта, финальный этап `PREP_STOCK`.
3. **Имена маршрутов** — три варианта дают три разных имени (иначе делили бы маршрут).
4. **Операции строк из колонок файла** (`resolve_operations`) — `DRILL` / `PRESS_WINDOW`
   / `PRESS_COMB`; дефолт участка как fallback — `SHOT`.
5. **Импорт → позиции** — файл новым шаблоном даёт три позиции, у каждой маршрут
   нужного варианта; количество позиции берётся из файла.

### E2E

- `frontend/e2e/testdata/План подготовительного участка.xlsx` — новый файл, закоммичен.
- `frontend/e2e/prep-stage-plan.spec.ts` — самый длинный вариант (сверло + дробеструй):
  импорт новым шаблоном → approve → запуск → круг «передачи ↔ участки» → ассерт
  «материал на `PREP_STOCK`» (остаток по API) и «последний адресат цепочки передач —
  Склад подготовки».
- `frontend/e2e/ui-helpers.ts` — `PREP_STAGE_PLAN_XLS_PATH` и
  `uploadPlanWithTemplateViaUI` (импорт ВЫБРАННЫМ шаблоном; отдельная функция, а не
  параметр, потому что в `uploadTestFileViaUI` имя шаблона зашито в два места).

## Доказательства

`frontend/e2e/ui-helpers.ts` **не тронут**: этот файл правит параллельный срез
(#312), и правка общей инфраструктуры разошлась бы при слиянии. Фикстура и
загрузчик объявлены прямо в `prep-stage-plan.spec.ts`.

## Про `is_final` на `PREP_STOCK` (вопрос оркестратора)

Опасение: `route_builder.py:420-421` помечает финальным последний шаг, а
`WorkTask` создаются только для production-участков (`plan_generation.py:288`),
и на транзитном `PREP_STOCK` задания нет.

Проверено чтением и тестом, продуктовое решение **не требуется**:
`route_builder.py:420-421` ставит `steps[-1].is_final = True` безусловно — по
позиции в списке, а не по типу секции. Тест
`test_each_file_variant_builds_its_own_route` ассертит этот флаг для всех
вариантов. `final_release` на `PREP_STOCK` и не должен вызываться: секция
`wip_stock` с `is_output_default=False` — не «склад выпуска». Материал остаётся
на участке как завершённый остаток, что и проверяет ассерт спеки.

| Проверка | Команда | Результат |
|----------|---------|-----------|
| Целостность сидов | `pytest tests/test_seed_integrity.py` | 46 passed |
| Новые тесты #313 | `pytest tests/test_prep_stage_plan_import.py` | 15 passed |
| Полный pytest | `scripts/test-run.ps1` (launcher, изолированная БД) | см. комментарий к тикету |
| Типы frontend | `npx tsc -p tsconfig.json --noEmit` | 0 ошибок |

## Осталось

- Полный прогон `npm run test:e2e` на стенде (`--retries=0`, `workers=1`, `CI` пуст) —
  выполняется силами ночного стенда; отчёт с SHA в комментарии к тикету.
- Посев сидов на devstack — за человеком (агент devstack не поднимает).
  Команда: `npm run db:seed` из корня репозитория.
## Прогон e2e (SHA `000d06a5`) — КРАСНЫЙ, мой тест

Команда: `E2E_MAX_PARALLEL_RUNS=3 E2E_ENV_FILE=.env.e2e.night-313.local CI= \
npm run test:e2e -- --retries=0 --workers=1` → ярус `all`, 323 с, код 1.
Единственный упавший тест во всём прогоне — мой:
`prep-stage-plan.spec.ts` → «импорт новым шаблоном → задания → материал на
складе подготовки».

Причина (из `error-context.md`):

```
Error: строка «#14 ЮП-009 — 300 шт. Сверловка 0/300 Передать»
       осталась в списке после «Передать»
Expected: 0  Received: 1
```

Маршрут собран верно (`Сверловка - Дробеструй`, профиль `prep_stage_plan`),
импорт новым шаблоном отработал, позиция создана, approve и запуск прошли.
Не проходит ПЕРВАЯ передача `RAW_STOCK → DRILLING`: у задания на сверловке
`0/300` — материал на участок не выдан, поэтому строка «Передать» не уходит
из ready-списка и `sendReadyTransfersViaUI` возвращает 0.

По симптому это тот же класс, что оркестратор уже разбирает по
`transfers-auto-accept.spec.ts` (предвыбор источника передачи), и он не связан
с сидами #313: дело в выдаче сырья на первое задание маршрута. Отличить
свою правку от общей регрессии без зелёного стенда нельзя — фиксирую как есть.

Что нужно следующему: разобраться с выдачей материала на первое задание
подготовительного маршрута (или с общим предвыбором источника) и перепрогнать
спеку. Без этого AC «материал на PREP_STOCK» закрыть нельзя.

## Честный итог DoD

| Пункт | Статус |
|-------|--------|
| Полный pytest через launcher | **2090 passed, 2 failed** → оба починены (`test_route_steps_preview` брал чужие правила), перепроверено точечно: 106 passed. Повторного ПОЛНОГО прогона после починки не было. |
| Полный e2e | красный, 1 упавший тест — мой, причина разобрана выше |
| `npx tsc --noEmit` | 0 ошибок |
| `ruff check .` (backend целиком) | All checks passed |
| `codegraph sync` | Synced 3 changed files, 81 nodes |
