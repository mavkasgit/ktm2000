# T-297 / T-298 / T-296 — замеры «до» для волны 2

Подготовка волны 2, **код не трогал**. Только измерение на dev-данных.
Методика та же, что в #290: прямой вызов ручки/сервис-функции в транзакции с
`rollback`, счёт SQL — engine-слушатель `before_cursor_execute`/`after_cursor_execute`.
БД владельца `:5440/ktm2000_prod` открывалась только на SELECT и не мигрировалась.

Мералка: `docs/night/logs/t297_measure_before.py`, сырой вывод: `t297_before.json`.
Замеры под нагрузкой (на машине 4 агента) — время вторично, основная метрика
**число SQL-запросов** (от нагрузки не зависит).

## Объём dev-данных, на котором снято «до»

| Таблица | Строк |
|---|---|
| `plan_positions` | 91 (все 91 — у плана `id=6`, статус `released`) |
| `production_plans` | 1 (неудалённых) |
| `import_batches` | 1 (`id=6`, с 91 позицией) |
| `work_tasks` | 587 |
| `section_plan_lines` | 804 |
| `stock_transactions` | 892 |

## Сводка

| Эндпоинт | SQL | разных форм | строк ответа | SQL-мс | wall-мс |
|---|---|---|---|---|---|
| `/production-planning/rows` limit=100 | **1909** | 24 | 91 | 2935.8 | 5087.0 |
| `/production-planning/rows` limit=500 | **1909** | 24 | 91 | 2834.9 | 4926.7 |
| `/production-planning/overview` | **2723** | 21 | 6 разделов | 3655.4 | 6652.8 |
| `/production-plans` | 3 | 3 | 1 | 25.0 | 35.4 |
| `/production-plans/6/all-positions` | 3 | 3 | **0** | 27.7 | 40.4 |
| `/production-plans/all-positions` limit=500 | 2 | 2 | **0** | 9.5 | 20.9 |
| `/imports/6/positions` | **1796** | 16 | 91 | 2113.4 | 3644.0 |

## Две оговорки, важные для честности сравнения

**1. `rows limit=100` и `limit=500` дали одинаковые 1909 запросов.** В dev-данных
всего 91 позиция, лимит не связывает — страница возвращает всё и при 100, и при 500.
Число запросов масштабируется по числу позиций, а не по `limit`. Когда появится
план на 500+ позиций, разница станет видна; сейчас эти два замера — один и тот же
сценарий. Проверять эффект от пагинации (#297) на dev-данных бессмысленно —
нужен либо клон с раздутым `plan_positions`, либо тестовая БД.

**2. Оба `all-positions` вернули 0 строк.** Все 91 позиция имеют статус
`released`, а обе ручки фильтруют по `ALL_POSITIONS_PLANNING_STATUSES`
(`draft`/`invalid`/`valid`). Плана с ≥50 позициями в статусе планирования в
dev-данных нет — есть только план на 91 позицию, но он весь `released`.
Поэтому «до» для `/production-plans/{id}/all-positions` (#296, если он про эту
ручку) снять на dev-данных **невозможно**: сценарий пустой, 3 запроса на 0 строк
не показывают ничего. Замерять #296 придётся на тестовой БД с сидами.

Зато эти два замера полезны как **верхняя граница**: ручка без N+1 держится
на 2–3 запросах независимо от числа планов. Если после правки #296 ручка
на 500 позициях уйдёт за 10 запросов — это регресс, а не улучшение.

## Профиль верхних запросов по числу вызовов (карта работы для #297/#298)

### `/production-planning/rows` (1909 запросов на 91 строку)

| Вызовов | Форма запроса | Комментарий |
|---|---|---|
| 215 | `section_operations` по `section_id` | `lazy="selectin"` на `Section.operations` |
| 215 | `spg_sections` join `storage_production_groups` | `lazy="selectin"` на `Section.spg_links` |
| 215 | `user_sections` join `users` | `lazy="selectin"` на `Section.users` |
| 183 | `section_operations` по `id` | дубль предыдущей выборки, другой путь |
| 182 | `sections` (все колонки) | **по одной секции на строку** |
| 125 | `route_operations` по `route_stage_id IN (...)` | `RouteStage.operations` |
| 92 | `EXISTS product_pairs` по `products.id` | `product_pairs` без индекса |
| 91 | `route_rule_profiles` по `id` | резолв маршрута, по позиции |
| 91 | `route_selection_rules` по `profile_id IN (...)` | резолв маршрута |
| 91 | `route_selection_rules` по `is_active AND (profile_id IS NULL OR = …)` | резолв маршрута |

### `/production-planning/overview` (2723 запроса на 6 разделов)

| Вызовов | Форма запроса | Комментарий |
|---|---|---|
| **307** | `stock_transactions … WHERE task_id = $1 GROUP BY reason` | **кэш задачи, по одному запросу на задачу** |
| **307** | `task_cache_send_sq.net_quantity` | **то же, net по TRANSFER_SEND** |
| **307** | `task_cache_recv_sq.net_quantity` | **то же, net по TRANSFER_RECEIVE** |
| 183 | `sections` | по секции на строку |
| 183 | `section_operations` | `lazy="selectin"` |
| 183 | `spg_sections` | `lazy="selectin"` |
| 183 | `user_sections` join `users` | `lazy="selectin"` |
| 182 | `section_operations` по `id` | дубль |
| 124 | `route_operations` | `RouteStage.operations` |
| 91 | `route_rule_profiles` | резолв маршрута |

### `/imports/6/positions` (1796 запросов на 91 строку)

| Вызовов | Форма запроса | Комментарий |
|---|---|---|
| 182 | `sections` | **по секции на строку** |
| 182 | `section_operations` (×2 формы) | `lazy="selectin"` + дубль |
| 182 | `spg_sections` | `lazy="selectin"` |
| 182 | `user_sections` join `users` | `lazy="selectin"` |
| 156 | `EXISTS product_pairs` | `db.get(Product)` тянет pairs |
| 91 | `route_rule_profiles` | `resolve_position_route` — вызывается на позицию |
| 91 | `route_selection_rules` (×2 формы) | там же |
| 91 | `product_processing_flags` join `processing_flags` | `Product` collection |

## Главная находка: корень N+1 один на все три эндпоинта

`Section` (`app/models/section.py:48-50`) объявляет **три** связи с
`lazy="selectin"`:

```python
users      = relationship("User", secondary="user_sections", …, lazy="selectin")
operations = relationship("SectionOperation", …,                        lazy="selectin")
spg_links  = relationship("StorageProductionGroup", secondary="spg_sections", …, lazy="selectin")
```

`lazy="selectin"` срабатывает **на каждый загруженный экземпляр**, а не на запрос:
когда код в цикле подтягивает секции по одной (`db.get(Section, id)` или через
связь), каждая из 182 загрузок порождает 3 дочерних запроса. Отсюда
182 + 182 + 182 + 215 и ≈1000 запросов на один экран.

Это объясняет, почему `rows`, `overview` и `imports/{id}/positions` упираются
в одно и то же число ≈180–215 при разном числе строк: **стоимость пропорциональна
числу загрузок секций, а не числу строк ответа**.

**Что это даёт #297/#298:** узкое место — не в самих запросах, а в их количестве.
Индексы (мой #291) здесь не помогут: каждый из 182 запросов идёт по primary key
и уже оптимален. Единственное лечение — **перестать грузить секции по одной**:
собрать множество `section_id` и взять их одним `IN` (или `selectinload` на
уровне родительской выборки), что превращает ~1000 запросов в 3–4.

**Отдельно про `overview`:** 921 запрос из 2723 — это три вызова кэша задачи на
каждую из 307 задач (`task_cache_send_sq`, `task_cache_recv_sq`, агрегат по
`reason`). Подтверждено по коду: в цикле зовётся scalar-ветка
`production_planning.py:541` (`pm.get_task_cache(db, wt.id)`), тогда как в 1879
того же файла уже используется bulk `pm.get_tasks_cache_bulk(db, all_wt_ids)` —
готовый инструмент в проекте есть, `overview` его не зовёт. Это самый крупный
и самый дешёвый для исправления кусок: один существующий bulk-метод вместо
921 запроса.

## Что НЕ трогал

Ни одной строки кода: этот шаг — только измерение. Коммит содержит один файл
`docs/night/tickets/T-297-298-296-measure-before.md`; меркалка и JSON живут в
`docs/night/logs/`, который в `.gitignore`.
