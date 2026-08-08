# ADR-0004: Типизированный канон сидов (PlantConfig)

Дата: 2026-08-02. Статус: принято.

## Контекст

Заводские справочники и политики живут в двух несогласованных ярусах:

1. **БД-канон** (runtime): `selection_rules`, `route_rule_profiles`, `sections`,
   `spgs`, `import_templates` — seeded из Python-dict, читаются движком из БД,
   редактируются админом через UI.
2. **Код-данные** (release-time): `plant_policies.py` (токены цвета, тексты
   ошибок, правило подвески, paired/standart processing) — сервисы импортируют
   напрямую, нет ни схемы, ни валидации, ни реестра.

Проблемы:

- Dict-суп: опечатка в коде участка/операции ловится только в рантайме.
- Нет единого реестра «вот все справочники завода».
- Сервисные хардкоды (SCRAP on-the-fly, `_get_stock_location`, карта брака
  127 строк if/else, `ROUTE_ERROR_CODES` — мёртвый дубль ключей
  `plant_policies`) не вынесены в данные.
- 6 дублей словарей «код → RU-лейбл» на фронте.
- Нет fail-fast: приложение стартует с битыми seed-данными.

## Решение

### 1. PlantConfig — типизированный объект заводской конфигурации

```python
class PlantConfig(BaseModel):
    production: ProductionCanon
    routing: RoutingCanon
    quality: QualityCanon
    display: DisplayCanon
    import_templates: list[ImportTemplateDef]
```

Доменные суб-модели:

| Канон | Содержимое |
|-------|-----------|
| `ProductionCanon` | sections, ops, scrap_policy, stock_locations |
| `RoutingCanon` | selection_rules, route_rule_profiles, spgs |
| `QualityCanon` | defect_decision_map |
| `DisplayCanon` | labels, colors, roles |

### 2. Граница код-канон vs БД-канон

Критерий: **«Нужна ли мутация между релизами без деплоя?»**

- **Да** → БД (runtime canon). Code-seed задаёт default shape (typed,
  validated), admin правит через UI. Drift допустим до следующего re-seed.
- **Нет** → Код (sole canon). Нет DB-записи, нет UI-эндпоинта.

Внутри код-канона: заводо-зависимое → typed seed layer (PlantConfig),
универсальное → core constants (но валидируется тем же реестром).

### 3. Шов конвертации (authoring vs runtime representation)

- **Существующие данные** (SELECTION_RULES, SECTIONS_DATA): dict-литералы
  не трогаем. Реестр при загрузке конвертирует: `[Model.model_validate(d)
  for d in RAW]`. Downstream видит модели.
- **Новые выносы** (SCRAP, DefectType, карта брака, лейблы): авторятся
  сразу как конструкторы моделей. IDE ловит ошибку формы при написании.

Accessor всегда возвращает модели — это «единый язык».

### 4. Валидация = часть конструирования

`build_plant_config()` собирает + валидирует в одном вызове. Объект не может
существовать в невалидном виде. Cross-ref проверки (8 правил):

1. Все `section_code` в правилах/профилях/SPG существуют в SECTIONS.
2. Нет дублей `code` в каждом наборе.
3. Обязательные поля не пустые.
4. `operation_code` в SECTION_OPS принадлежит своему section.
5. `import_template_code` в профиле существует в IMPORT_TEMPLATES.
6. Enum-поля (type, operator, phase) содержат только допустимые значения.
7. Priority ≥ 0.
8. Actions rules ссылаются на существующие `section_id`.

Точки вызова:

- FastAPI lifespan → `app.state` (приложение не стартует с битыми данными).
- Session-scoped fixture в тестах.
- `validate_seeds.py` в CI (тонкая обёртка, тот же код).

### 5. Доступ сервисов (DI)

- `Depends()` на границе роута / composition root. Сервис получает
  `PlantConfig` (или доменный суб-канон) в конструктор.
- Non-FastAPI контексты (сидеры, CLI): явная фабрика на entrypoint,
  прокидывается аргументом.
- Правило: только composition root строит/резолвит PlantConfig. Ничто
  в середине стека не импортирует accessor напрямую.
- Multi-plant отложен: `build_plant_config()` без параметров, один завод.
- **Уточнение ADR-0008:** разрешён eagerly resolved immutable snapshot
  (module-level `DEFAULT = _build().x`) для leaf-функций и snapshot-констант
  при соблюдении критериев ADR-0008. Запрет на `build_plant_config()` внутри
  тела функции вне composition root — сохранён и кодифицирован gate-тестом
  (`tests/test_canon_access_gate.py`).

### 6. Сидеры потребляют PlantConfig

`run_full_seed(db, config)` → каждый сидер получает типизированные модели.
Re-seed всегда перезаписывает (seed = source of truth, admin drift временный).

### 7. API write-валидация

Эндпоинты, пишущие rules/profiles/sections, валидируют payload против
pydantic-моделей из canon + явный cross-ref против текущего состояния БД
(`_validate_cross_refs_against_db`). JSONB conditions/actions типизированы
вложенно (discriminated union), не `dict`.

### 8. Лейблы и фронтенд

- Единый источник: `LabelsCanon` в PlantConfig (сервер использует напрямую).
- Фронтенд: генерация `frontend/shared/lib/labels.ts` из LabelsCanon на
  CI/build (скрипт `generate_frontend_labels.py`). Не runtime-запрос.
- 6 дублей на фронте → импорт из одного сгенерированного файла.

### 9. Тестирование

- `test_seed_integrity.py` — gate: грузит РЕАЛЬНЫЕ данные, проверяет 8
  cross-ref правил. Запускается первым в CI.
- Per-consumer тесты с fake PlantConfig — проверяют, что сервис не хардкодит
  значения (fake ≠ prod → если проходит, сервис универсален).

### 10. Порядок поставки

1. **plant_policies** (tracer bullet): canon/ инфраструктура + DI + accessor.
2. **Sections + Ops**: связный узел, cross-ref в бою.
3. **Selection rules + profiles**: типизация JSONB, API-валидация.
4. **Сервисные выносы**: SCRAP, stock_location, defect_map.
5. **Labels + roles + TS-генерация**.

## Критерий «параметр vs оператор» (для выноса хардкодов)

- **Параметр** (конкретные коды, названия, тексты) → PlantConfig.
- **Оператор** (форма рассуждения, инварианты, диспетчеризация) → сервис.
- Проверка: убрать конкретные значения — осталась осмысленная функция?
  Да = оператор + данные. Нет = всё было данными.

## Отклонённые альтернативы

- **Всё в БД** (plant_policies как таблица): миграция + API + обновление
  потребителей без явного требования. Отложено до реального второго завода.
- **Всё в код** (перенос rules/profiles из БД): ломает UI-эндпоинты и
  движок правил, лишает admin hotfix. Регресс.
- **Пустое ядро** (полная реархитектура seed-loader): over-engineering
  без реальной второй инсталляции. Инкрементальный вынос покрывает цель.
- **Module-level lazy accessor**: хрупко при pytest-xdist, невозможно
  для multi-tenant без contextvar-магии.
- **Адаптер поверх старого модуля**: нарушает правило «только composition
  root резолвит PlantConfig».

## Последствия

- Новый справочник добавляется по паттерну: модель → данные → реестр →
  accessor → сединер → integrity-тест.
- `ROUTE_ERROR_CODES` (мёртвый дубль) устраняется: становится derived
  из LabelsCanon.
- `ROLES_CATALOG` переезжает в `DisplayCanon.roles`.
- Демо-пользователи (planner, manager, operator, viewer) убраны из
  `run_full_seed`; остаются system + admin (break-glass) + akadmin.
  Демо — отдельный седер по необходимости.
- При изменении лейбла нужен деплой фронта (осознанный trade-off:
  лейблы классифицированы как «меняются релизом»).
