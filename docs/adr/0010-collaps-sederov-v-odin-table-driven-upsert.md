# ADR-0010: Коллапс седеров в один table-driven upsert

Статус: принято. Дата: 2026-08-08. Реализует ADR-0004 §6.

## Контекст

11 седеров повторяют один и тот же паттерн `select-by-code → update/insert → flush`
с интерфейсом ≈ реализация. section-code→id резолв построен независимо в 4 местах
(routes_seeder ×2, selection_rules_seeder, run_seed), op-конверсия существует дважды
(`_convert_section_ops` в registry и `_convert_raw_ops` в sections_seeder).
Backward-compat raw-dict путь жив в sections/processing_flags/dimension_types/
import_template/routes.

## Решение

Один модуль `upsert_by_key(db, Model, rows, key_field, field_map, resolve=...)`,
возвращающий `dict[key, Model]`. Скалярные седеры (sections, defect_types,
route_rule_profile, import_template, processing_flags, dimension_types) становятся
тонкими обёртками над хелпером, `field_map` живёт рядом с данными в
authoring-модулях. Сложные седеры (spgs, selection_rules, routes, users, cleanup,
demo) остаются bespoke-функциями, но section-code→id резолв single-sourced в
run_seed и передаётся параметром. SectionOperation upsertится через хелпер по
составному ключу `(section_id, operation_code)`, `transforms_dimensions`
вычисляется до вызова. Все данные переезжают в authoring-модули, raw-dict
backward-compat умирает, конвертер остаётся один (registry).

## Considered Options

- **Полный мета-модуль (все 11 седеров как данные):** отклонено — spgs/routes/
  selection_rules/users имеют нетривиальные отношения (биндинги, FK-резолв,
  replace-каскад этапов, пининг id), не выражаемые поле-мапой; «интерфейс ≈
  реализация» переедет в сам хелпер.
- **Ключ только строковый (`key_field: str`):** отклонено — SectionOperation
  требует составного ключа; вместо усложнения хелпера составные ключи
  разрешены, производные поля вычисляются перед вызовом.
- **Хелпер с `return_mode`/режимами:** отклонено — флаг-переключатель вместо
  кода; map — самая богатая форма, count/single из неё дешевы.
- **Спрятанный контекст/сервис для sections_map:** отклонено — map строится в
  run_seed и передаётся явным параметром.

## Consequences

- Новый справочник = данные в authoring-модуле + запись в canon, а не 4 файла.
- Дубли `_convert_*` и section-code→id резолв физически исчезают.
- `run_seed` остаётся оркестрацией (порядок, зависимость map), не несёт field_map.
- Седеры — чистые функции с обязательными параметрами: никаких скрытых
  дефолтов (`sections=None`/`production=None`/`sections_map=None`) и DB-load
  fallback-резолвов; `_DEFAULT_PRODUCTION` на импорте не существует. Данные
  для сида приходят всегда явно из run_seed.
- Тесты сидов обновлены осознанно: прямые вызовы седеров передают канон
  (`build_plant_config()`) или локальный section_map явно — не полагаются
  на дефолты.
