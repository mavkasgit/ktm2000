# T-303 (шаг 2, продолжение) — справочники маршрутов и разделов колонками

## Что было

Два места в общем коде маршрутов грузили **все** участки как ORM-объекты:

- `app/services/route_builder.py:144` — `select(Section)` без фильтра;
- `app/services/route_selection.py:551` — то же в снимке подбора маршрутов.

Каждая такая загрузка стоит **четырёх** запросов, а не одного: у модели `Section`
три связи с `lazy="selectin"` (`users`, `operations`, `spg_links`), и `selectin`
срабатывает на каждый загруженный экземпляр. Это тот остаток, который я зафиксировал
в #296 как «не мой файл» и оставил на конец ночи.

Хуже всего то, что эти вызовы идут на **каждый** резолв маршрутов, а резолв идёт
на каждую позицию: остаток множился на пять ручек (`rows`, `overview`,
`imports`, `section-totals`, `all-positions`) плюс `app/transfers/`.

## Что читается из этих объектов — по коду, не по профилю

Профиля здесь недостаточно: в прошлый раз ветка «позиция без задач стоит в очереди»
не исполнилась на dev-данных, и я по профилю решил, что `operations` не нужны,
а они нужны. Поэтому здесь выписано по коду, что именно читается:

| Потребитель | Читаемые поля |
|---|---|
| `route_builder.build_route_from_profile` | `section.id`, `section.code`, `section.name`, `section.type`, плюс `is_storage_section(section)` → `section.type` |
| `route_builder.load_route_build_batch_cache` | `section.id`, `section.code` |
| `route_selection._section_dicts` | `section.code`, `section.name` |
| `route_storage_classifier.*` | `section.type`, `section.name` |

Итого ровно **четыре** поля: `id`, `code`, `name`, `type`. Больше из участка в
маршрутных сервисах не читается ничего — проверено grep'ом по всем употреблениям
`section.` в обоих модулях и классификаторе.

## Что сделано

Новый модуль `app/services/section_ref.py`:

- `SectionRef` — frozen dataclass с полями `id`, `code`, `name`, `type`;
- `load_section_refs(db, ids=…, codes=…)` — выборка колонок, возвращает
  `dict[int, SectionRef]`;
- `SECTION_REF_COLUMNS` — явный список полей, чтобы «проекция» не разъехалась
  с реальностью при правке модели.

Переведены на неё:

- `route_builder.load_route_build_batch_cache` (строка 144);
- `route_builder.build_route_from_profile` — ветка без батч-кэша (строка 278);
- `route_selection.load_route_selection_batch_cache` (строка 551);
- `route_selection._sections_by_id` — тот же не-батчевый путь.

Аннотации `sections_by_id` / `sections_by_code` в обоих кэшах стали
`SectionRef` вместо `Section`.

`route_storage_classifier`: аннотации параметров расширены до
`SectionLike = Union[Section, SectionRef]` — классификаторы читают только
`.type` и `.name`, оба поля в проекции есть. Сама логика не менялась.

`raiseload` не использовался: объекты в этих путях не нужны вовсе.

## Замер

Dev-данные `:5440/ktm2000_prod`, только SELECT, транзакция с `rollback`.
«До» снято `git stash`-снятием этой же правки на той же БД.

| Ручка | SQL до | SQL после | дельта |
|---|---|---|---|
| `/production-planning/rows` limit=100 | 37 | **34** | −3 |
| `/production-planning/rows` limit=500 | 37 | **34** | −3 |
| `/production-planning/overview` | 32 | **29** | −3 |
| `/imports/{id}/positions` | 23 | **20** | −3 |
| `/production-plans` | 2 | 2 | — |
| `/{id}/all-positions` | 3 | 3 | — |
| `/all-positions` limit=500 | 2 | 2 | — |

Минус ровно три запроса на каждый вызов резолва: `Section` плюс три его
selectin-связи схлопнулись в одну выборку колонок.

**Порог регрессии в 10 запросов — пройден с запасом.** На клоне с батчем
в 900 позиций: `/imports/{id}/positions` даёт **23 → 20** SQL, то есть AC из #296
(≤ 20) впервые выполняется. wall 638.9 → 578.3 мс. Ответ — тот же.

## Ответ не изменился

- `/production-planning/rows`, пять сценариев (default 100/500, sort,
  status, offset): SHA-256 совпали с базовыми из #297 — `cbfe06750feab9a0`,
  `e169c0fa7f7de097`, `e18cd251710ea9b6`, `cbfe06750feab9a0`, `dc41ab60db46a116`.
- `/imports/{id}/positions` на 900 позициях: `0a1503f7306805a3` до и после.

Побайтово идентично.

## Границы (что НЕ трогал)

- `app/transfers/**` — срез A.
- `app/services/shopfloor/queries_sections.py` (`summary`, `board`) — срез D.
- `api/routes/route_selection_rules.py` — там своя префетч-структура со
  своими ORM-`Section`, другой ручкой (#294, срез A).
- Сиды и `demo_production_seeder` — у них свои локальные `sections_by_id`.
- Логика подбора и сборки маршрутов не менялась: только форма чтения.

## Проверки

- `npm run test:pytest` (PYTEST_NUM_WORKERS=2) — зелёный, ≥2032;
- `ruff check backend` — зелёный;
- миграций нет.

## Откат

Revert коммита. Новый модуль `section_ref.py` удаляется вместе с ним.
