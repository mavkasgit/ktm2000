# Паспорт маршрутов импорта Excel + ручной E2E прогон

## 1) Цель и рамки

Документ фиксирует:

- как из Excel формируется маршрутная информация для позиции плана;
- где и как происходит резолв маршрута (`manual > auto`);
- как валидируется соответствие импорта и маршрута;
- как вручную проверить это через тестовый прогон по стадиям.

## 2) Источники логики в коде

- Парсинг Excel: `backend/app/services/excel_import.py`
- Формирование change set: `backend/app/services/plan_import_service.py`
- Резолв маршрута: `backend/app/services/route_matcher.py`
- Сигнатура ожидаемого маршрута из payload: `backend/app/services/route_resolution.py`
- Валидация соответствия маршрута: `backend/app/services/route_validation.py`
- Staged test-run API: `backend/app/api/routes/demo.py`
- UI запуска тестового прогона: `frontend/src/features/planning/ImportWizard.tsx`
- UI ручного выполнения шагов: `frontend/src/features/sections/pages/SectionsTasksPage.tsx`
- UI контроля прогресса по этапам: `frontend/src/features/execution/pages/ExecutionPage.tsx`

## 3) Как из Excel рождается маршрутный контекст

### 3.1 Поля Excel -> payload позиции

При парсинге строки Excel в `source_payload` пишутся ключевые поля для маршрута:

- `operation` (сырой текст из колонки «Пробивка/сверловка»)
- `operation_code` (нормализованный код)
- `additional_pack_operations` (доп. упаковочные операции)
- `output_kind` (`finished_good` или `semi_finished_shipment`)

Нормализация `operation` в `operation_code`:

- содержит `окн` -> `PRESS_WINDOW`
- содержит `греб` -> `PRESS_COMB`
- содержит `сверл`/`сверло` -> `DRILL`
- содержит `клей` -> `PACK` + `PACK_GLUE`
- содержит `рассеив` -> `PACK` + `PACK_DIFFUSER`
- прочее -> `PACK` + `PACK_CUSTOM`
- пусто -> `None`

Нормализация `output_kind` (колонка «Вид конечного продукта»):

- `ГП` -> `finished_good`
- `П/ф` -> `semi_finished_shipment`

### 3.2 Матрица влияния параметров Excel на ожидаемую ветку маршрута

| Параметр в payload | Влияние на ожидаемую сигнатуру | Что проверяется |
|---|---|---|
| `operation_code=DRILL/PRESS_WINDOW/PRESS_COMB` | В сигнатуру добавляется первичная операция после `ISSUE_RAW` | Наличие/соответствие primary operation (`route_primary_operation_mismatch`) |
| `operation_code` отсутствует | Primary operation не требуется как отдельный шаг | При наличии неожиданной primary operation — mismatch |
| `output_kind=semi_finished_shipment` | После `ANOD` прямая ветка в final (без WIP) | Проверка branch (`route_not_matching_import_signature`) |
| `output_kind=finished_good` | После `ANOD` WIP-ветка (`WIP_WH`/`INTER`) и далее `SAW/PACK/final` | Проверка branch (`route_not_matching_import_signature`) |
| `additional_pack_operations` непустой | Должен быть `PACK` шаг; коды должны быть поддерживаемыми | `route_missing_required_step`, `route_missing_pack_additional_operation` |

## 3.3 Стандартный маршрут: 11 участков

Система определяет 11 стандартных участков (`sections_seed.py`):

| # | Code | Название | Kind | Роль в маршруте |
|---|---|---|---|---|
| 1 | `WH` | Склад сырья | `raw_stock` | Выдача сырья (`ISSUE_RAW`) |
| 2 | `DRILL` | Сверловка | `production` | Первичная операция при `operation_code=DRILL` |
| 3 | `PRESS` | Пресс | `production` | Первичная операция при `PRESS_WINDOW`/`PRESS_COMB` |
| 4 | `SHOT` | Дробеструй | `production` | Обязательный шаг (кроме артикулов без дробеструя) |
| 5 | `ANOD` | Анодирование | `production` | Обязательный шаг для всех маршрутов |
| 6 | `WIP_WH` | Склад полуфабриката | `wip_stock` | Только для `finished_good` |
| 7 | `SAW` | Пила | `production` | Только для `finished_good` |
| 8 | `PACK` | Упаковка | `production` | Только для `finished_good`; может иметь доп. операции |
| 9 | `FG_WH` | Склад готовой продукции | `finished_stock` | Приемка ГП/ПФ — всегда |
| 10 | `SHIPMENT` | К отгрузке | `finished_stock` | Ящики с ГП/ПФ — всегда |
| 11 | `SENT` | Отправлено | `finished_stock` | Отгруженная продукция — всегда |

### 3.3.1 Базовая последовательность (скелет)

```
WH → [PRIMARY_OP] → SHOT → ANOD → BRANCH → FG_WH → SHIPMENT → SENT
```

Где:
- `[PRIMARY_OP]` — опционально: `DRILL` или `PRESS` (зависит от `operation_code` из Excel)
- `BRANCH` — зависит от `output_kind`: П/ф → сразу FG_WH, ГП → WIP_WH → SAW → PACK → FG_WH

### 3.3.2 Два варианта ветки после ANOD

Колонка `Вид конечного продукта` из Excel определяет ветку:

**Вариант A: `output_kind=semi_finished_shipment` (П/ф)**

```
WH → [PRIMARY_OP] → SHOT → ANOD → FG_WH → SHIPMENT → SENT
```

**Вариант B: `output_kind=finished_good` (ГП)**

```
WH → [PRIMARY_OP] → SHOT → ANOD → WIP_WH → SAW → PACK → FG_WH → SHIPMENT → SENT
```

> `FG_WH`, `SHIPMENT`, `SENT` — финальные точки, присутствуют в любом маршруте.

### 3.3.3 Влияние operation_code на маршрут

| operation_code из Excel | Primary Op шаг | Последовательность (ГП) |
|---|---|---|
| `None` (пусто) | Нет | WH → SHOT → ANOD → WIP_WH → SAW → PACK → FG_WH → SHIPMENT → SENT |
| `DRILL` | `DRILL` | WH → DRILL → SHOT → ANOD → WIP_WH → SAW → PACK → FG_WH → SHIPMENT → SENT |
| `PRESS_WINDOW` | `PRESS` | WH → PRESS → SHOT → ANOD → WIP_WH → SAW → PACK → FG_WH → SHIPMENT → SENT |
| `PRESS_COMB` | `PRESS` | WH → PRESS → SHOT → ANOD → WIP_WH → SAW → PACK → FG_WH → SHIPMENT → SENT |

### 3.3.4 Дополнительные упаковочные операции

`additional_pack_operations` — атрибуты шага `PACK`, не самостоятельные шаги:

| Код доп. операции | Когда | Что означает |
|---|---|---|
| `PACK_GLUE` | `operation` содержит "клей" | Упаковка с клеевой операцией |
| `PACK_DIFFUSER` | `operation` содержит "рассеив" | Упаковка с рассеивателем |
| `PACK_CUSTOM` | прочее значение `operation` | Кастомная упаковочная операция |

При валидации: если `additional_pack_operations` непустой → шаг `PACK` обязан присутствовать, коды должны быть поддерживаемыми.

### 3.3.5 Полная матрица маршрутов

_(Убрана: дублировала 3.3.3 и содержала неточности. Маршрут определяется комбинацией `operation_code` + `output_kind` из Excel — см. 3.3.2 и 3.3.3. Ограничения по участкам — см. 3.3.6.)_

### 3.3.6 Ограничения и исключения по участкам

| Участок | Всегда? | Условие включения | Правило группировки / расчёта |
|---|---|---|---|
| `WH` (Склад сырья) | **Всегда** | Нет | Одинаковый артикул = одна позиция на выдачу, независимо от маршрутных различий ниже |
| `DRILL` (Сверловка) | Условно | `Пробивка/сверловка` содержит `"сверло"` → `operation_code=DRILL` | Присутствует или пропускается полностью |
| `PRESS` (Пресс) | Условно | `Пробивка/сверловка` содержит `"окно"` (`PRESS_WINDOW`) или `"гребенка"` (`PRESS_COMB`) | **Критично:** `окно` и `гребенка` нельзя перемешивать. Один артикул с разными пресс-операциями = **две разные позиции** после WH. Группировка по артикулу только внутри одной пресс-операции |
| `SHOT` (Дробеструй) | Почти всегда | Пропускается если артикул в каталоге помечен «не дробеструится» | Для остальных — базово присутствует |
| `ANOD` (Анодирование) | **Всегда** | Нет | **Расчёт подвесов:** `кол-во на подвес` из каталога/техкарты. На подвес — только **одинаковый артикул + одинаковый цвет**. Если количество не кратно ёмкости → **округление вверх** до полного подвеса, плановое количество пересчитывается = `подвесы × ёмкость`. Пересчитанное значение записывается в строку плана с пометкой |
| `WIP_WH` | См. ветку | Только `output_kind=finished_good` (ГП) | — |
| `SAW` | См. ветку | Только `output_kind=finished_good` (ГП) | **Разделение по длине:** если `Длина после упак, м` различается — строка делится на отдельные позиции по каждой длине. Количество распределяется пропорционально |
| `PACK` | См. ветку | Только `output_kind=finished_good` (ГП) | **Разделение по длине:** если `Длина, м` различается — строка делится. Если длина уменьшена — количество увеличивается, строка пересчитывается с пометкой |
| `FG_WH` | **Всегда** | Финальная точка | — |
| `SHIPMENT` | **Всегда** | Присутствует в любом маршруте | — |
| `SENT` | **Всегда** | Присутствует в любом маршруте | — |

## 4) Резолв маршрута для позиции (policy: manual > auto)

### 4.1 Приоритет источника маршрута

1. Если у `PlanPosition.route_id` задано значение — ручной override (`manual`).
2. Если `route_id` не задан — `find_route()` по активным маршрутам и `route_matching_rules`.
3. Если ничего не найдено — маршрут `missing`.

### 4.2 Текущий dev runtime

На dev (2026-05-10) в `production_routes` есть активные маршруты, но в `route_matching_rules` записей нет.

Следствие: авто-резолв уходит в fallback — берётся первый активный маршрут по `id`.

Это рабочий режим, но для предсказуемости нужно проставлять `route_id` явно.

## 5) Где и какие ошибки маршрута формируются

Точки проверки:

- базовая валидация позиции: `validate_plan_position()` в `plan_validation.py`
- сигнатурная проверка: `validate_route_match()` в `route_validation.py`
- endpoint диагностики: `GET /production-plans/{plan_id}/positions/{position_id}/route-check`

Типовые коды ошибок:

- `active_route_not_found`
- `active_route_has_no_steps`
- `route_sequence_invalid`
- `route_contains_inactive_section`
- `route_not_matching_import_signature`
- `route_missing_required_step`
- `route_missing_pack_additional_operation`
- `route_primary_operation_mismatch`

## 6) Ручной E2E сценарий тестового прогона (UI)

### 6.1 Подготовка

1. Открыть модалку тестового импорта в Planning UI (`ImportWizard`).
2. Выбрать: активную техкарту, активный маршрут, количество.
3. Для режима `to_step_ready` — выбрать `target_route_step_id`.

Рекомендация: для предсказуемого результата всегда выбирать маршрут вручную.

### 6.2 Проверка по `stage_preset`

Прогонять режимы последовательно:

1. `before_approve` — создана позиция, без approve/release, `tasks_created = 0`
2. `after_approve` — позиция в `approved`, задачи не созданы, `tasks_created = 0`
3. `after_release` — создан release batch + задачи, движения не выполнены, `tasks_created > 0`
4. `to_step_ready` — шаги до целевого пройдены, целевой в `ready`
5. `full_route` — полный автопроход, `stage_results` по каждому этапу, `stopped_at_stage = completed`

### 6.3 Что проверять в UI после запуска

1. `/execution` — строка появилась, статус/прогресс соответствует стадии
2. `/shopfloor-tasks/:sectionId` — для `after_release`/`to_step_ready` доступны задачи

## 7) Проверка соответствия маршрута импорту (`route-check`)

Для созданной позиции выполнить `route-check` и сверить:

- `expected_signature` (что ожидалось из Excel payload);
- `active_route_snapshot` (что реально назначено);
- `issues` (коды расхождений).

Критерий: `match=true` либо объяснимые `issues`, подтверждающие известное отличие.

## 8) Ручное "протыкивание" шагов

Сценарий применять на `after_release` или `to_step_ready`:

1. На нужном участке выполнить `Выдать` (`issue`)
2. Выполнить `Факт` (`complete`) с годным/браком
3. Выполнить `Передать` (`send`) на следующий этап
4. Повторять до нужной глубины маршрута
5. Контролировать статусы и проценты в `/execution`

## 9) Известные риски тестового контура

- падения `pytest` в `backend/tests/test_demo_full_route.py` (ошибки FK/rollback сессии);
- deadlock при setup части импортных тестов (`backend/tests/test_excel_import.py`, DDL `drop_all/create_all`).

Это не блокирует ручной dev E2E по UI; требуется отдельная задача: стабилизация CI/pytest.

## 10) Мини-чеклист приемки

- Документ отражает текущую policy: `manual > auto`
- Зафиксирован fallback при пустых `route_matching_rules`
- Есть матрица полей Excel -> ожидаемые ограничения маршрута
- Есть пошаговый ручной сценарий всех 5 `stage_preset`
- Есть раздел с известными рисками тестового контура
