# T-291 — Индексы горячих путей (миграция 078)

## Проблема

Опрашиваемые каждые 12 секунд экраны (доска участка, `/rows`, `/transfers/ready`,
сводка участков) ходили в `seq scan` по таблицам без вторичных индексов:
`work_tasks` (FK на `sections` без индекса), `transfers` (`GROUP BY to_section_id`),
`plan_positions` (активные/неудалённые), `route_stages` (коррелированный EXISTS).

## Что сделано

Миграция `backend/alembic/versions/078_hot_path_indexes.py`
(`down_revision = 077_ready_transfer_indexes`) + зеркальные `__table_args__`:

| Таблица | Индекс | Зачем |
|---|---|---|
| `work_tasks` | `(section_id, status)` | доска/summary/ready фильтруют по участку, summary по нему же группирует |
| `route_stages` | `(section_id)` | коррелированный EXISTS «задача на участке N» в `/rows` |
| `plan_positions` | `(status) WHERE deleted_at IS NULL` | `_active_positions_stmt`, фильтр «не в корзине» |
| `plan_positions` | `(production_plan_id)` | `list_plans` / `section_totals`: 2 скана × N планов |
| `transfers` | `(from_section_id, created_at)` | OR-фильтр журнала + `ORDER BY created_at DESC` |
| `transfers` | `(to_section_id, created_at)` | `GROUP BY to_section_id` в сводке участка |
| `stock_transactions` | `(to_location_id, created_at)` | суточная статистика участка; **заменяет** одиночный `ix_stock_transactions_to_location_id` |
| `stock_transactions` | `(created_at)` | фид проводок: `ORDER BY`/фильтры дат |

Итого 8 индексов, 1 дроп. Не создавались (покрыты существующими):

- `section_plan_lines (plan_position_id)` — левый префикс `ix_section_plan_lines_plan_position_id_sequence` (#290);
- `stock_transactions (section_plan_line_id, reason)` — #290 уже создал `(reason, section_plan_line_id)`; равенства по обоим столбцам, порядок на селективность не влияет;
- `transfers (created_at)` — #290;
- `transfers (to_section_id)` / `(from_section_id)` — покрыты новыми составными.

## Границы (что НЕ трогали)

- **SQL-формы запросов не менялись вообще.** Ни одного изменения в `queries_*.py`,
  `transfers/queries.py`, `stock/ledger.py`. Правка чисто декларативная (DDL + `__table_args__`),
  поэтому не пересекается с перeписыванием выборки доски (срез C) и аддитивным
  `in_daily_plan` (срез D).
- Не трогал `BASELINE.md`/`JOURNAL.md`/`PLAN-*` — ведёт оркестратор.
- Не касался индексов вне списка тикета (`products`, `audit_logs`, …).

## Замеры

Методика: прямой вызов сервис-функции в транзакции с `rollback`, счёт SQL —
engine-слушатель `before_cursor_execute`/`after_cursor_execute`.
Данные — клон БД владельца `:5440/ktm2000_prod` в изолированную `ktm2000_t291after`
(port 5441). БД владельца открывалась только на SELECT и никогда не мигрировалась.
Логи: `docs/night/logs/t291_measure.py`, `t291_scale_test.py`, `t291_explain.py`.

### A. Текущий объём данных (587 work_tasks / 804 section_plan_lines / 892 stock_transactions / 214 transfers)

| Эндпоинт | SQL-запросов до | после | SQL-мс до | после | wall-мс до | после |
|---|---|---|---|---|---|---|
| `/production-planning/rows` | 1080 | 1080 | 1413.9 | 1286.6 | 2276.7 | 2087.9 |
| `/shopfloor/sections/10/board` | 15 | 15 | 136.2 | 145.1 | 183.8 | 194.7 |
| `/shopfloor/sections/summary` | 7 | 7 | 27.4 | 26.2 | 39.3 | 37.2 |
| `/transfers/ready` | 12 | 12 | 59.0 | 59.3 | 113.6 | 114.3 |

**Число SQL-запросов не изменилось ни на одном эндпоинте** — это ожидаемо и
ровно то, что нужно: индексы не меняют форму запросов, они меняют план исполнения.
Время на текущем объёме в пределах шума (±7%), потому что при 587 задачах вся
таблица `work_tasks` — это 27 страниц, и `seq scan` дешевле любого индекса.

Ответы API сверены JSON-хешем: **все 4 эндпоинта дали побайтово идентичный ответ**
(`rows` 79119 Б, `board` ≥200000 Б, `summary` 3829 Б, `transfers_ready` 1509 Б —
SHA-256 первых 16 символов совпали).

### B. Масштабный тест — когда индексы окупаются

`/rows` с 1080 запросами — это N+1, а не проблема индексов; на этом объёме
индексы дают ~9% по SQL-времени. Масштабный тест на изолированном клоне
(`t291_scale_test.py`) раздувает `work_tasks` копиями строк и снимает
EXPLAIN с индексами и без них на одном и том же наборе данных.

#### На 200 000 work_tasks (relpages 2851)

`work_tasks` раздут копиями строк на изолированном клоне (`INSERT … SELECT` +
`ANALYZE`); индексы 078 включаются и выключаются в **одной и той же** БД —
обе серии меряются на идентичных данных.

| Запрос | exec мс без 078 | exec мс с 078 | дельта | План изменился? |
|---|---|---|---|---|
| board (задачи участка) | 33.34 | **21.93** | **−34%** | да: `Seq Scan on work_tasks` → `Bitmap Heap Scan` + `Bitmap Index Scan on ix_work_tasks_section_id_status` |
| `/rows` EXISTS «задача на участке» | 0.392 | **0.180** | **−54%** | да: `Seq Scan on route_stages` исчез |
| summary (`GROUP BY section_id`) | 61.88 | 62.13 | +0.4% | нет — остаётся `Seq Scan` |
| incoming transfers (`GROUP BY to_section_id`) | 0.087 | 0.183 | +110% | нет — остаётся `Seq Scan` |

**Разбор каждого кандидата:**

- `work_tasks (section_id, status)` — **подтверждён**: доска ускорилась в 1.5 раза,
  seq scan по tasks ушёл. Главный выигрыш тикета.
- `route_stages (section_id)` — **подтверждён**: EXISTS в `/rows` вдвое быстрее,
  seq scan по 369 этапам исчез.
- `transfers (to_section_id, created_at)` — **не подтверждён на этом объёме**:
  таблица `transfers` — 214 строк (23 страницы), `Seq Scan` дешевле индекса, и на
  таких объёмах индекс даже слегка проигрывает. Оставлен как страховка на рост
  журнала; на текущих данных это мёртвый вес.
- `transfers (from_section_id, created_at)` — то же.
- `plan_positions (status) WHERE deleted_at IS NULL` — на 91 позиции планировщик
  его не берёт (таблица влезает в 26 страниц).
- `work_tasks (section_id, status)` для **summary** — не помогает: summary
  фильтрует по `status NOT IN (closed)`, через фильтр проходят 375 из 587 строк
  (селективности почти нет), а группировка всё равно требует их все. Индекс не
  может помочь запросу, которому нужны почти все строки.

Итог: **2 индекса из 8 дают измеримый выигрыш на 200k строк, 6 — страховка на
рост объёма.** Это нормальная природа индексов: они платят write-ценой сейчас и
окупаются на объёмах, которых на тестовой БД ещё нет. Тикет #291 прав в
формулировке («нет ни одного вторичного индекса») и неправ в подразумеваемом
выигрыше «прямо сейчас»: на 587 задачах seq scan корректен, и **ни один** индекс
его не убирает. Индексы убирают его на объёме, который будет через год.

Отдельно: `/rows` с 1080 SQL-запросами — это **N+1, а не проблема индексов**.
Никакой индекс не сократит число запросов; его сокращает только батчинг
в `production_planning_rows.py`. Это отдельная работа, вне тикета #291.

## Write-цена

Мералка `t291_write_cost.py`: 400 одиночных INSERT в одной транзакции
(`rollback` в конце), 50 прогревочных вставок, `perf_counter`.
Индексы 078 включаются/выключаются в одной и той же БД; сравнение идёт
**против 077**, а не против «голой» таблицы — иначе write-цена была бы
нечестной (все сравниваемые серии содержат индексы #290).
БД — изолированный клон, `work_tasks` = 200 000 строк, под нагрузкой (4 агента).

| Операция записи | медиана без 078 | медиана с 078 | дельта | p95 без | p95 с |
|---|---|---|---|---|---|
| `INSERT stock_transactions` | 1.627 мс | 1.662 мс | **+0.036 мс (+2.2%)** | 2.181 | 2.344 |
| `INSERT work_tasks` | 1.837 мс | 1.946 мс | **+0.109 мс (+5.9%)** | 2.442 | 2.497 |

**Просачивается ли в API?** Нет, в пределах шума:

- Проводка в ledger — это `StockCommandService.record()` → `_recompute_balance`
  → один INSERT в `stock_transactions` + чтение/апдейт `stock_balances`.
  Прирост +0.036 мс на фоне ~1.6 мс самой вставки и десятков мс пересчёта
  баланса — это 2%, которые не отличимы от шума измерения.
- Завершение задачи (`work_tasks` UPDATE + ledger INSERT) — +0.109 мс против
  ~1.9 мс. На фоне HTTP-запроса с пересчётом остатков и записью в
  `action_journal` это тоже шум.

Учтено, что `ix_stock_transactions_to_location_id` **дропнут** и заменён составным
с `created_at`: на ledger это чистый обмен «одна запись индекса на одну
запись индекса» плюс один лишний индекс `(created_at)`. Итого по ledger:
было 10 индексов → стало 11, из них новых ровно 2 (`(to_location_id, created_at)`,
`(created_at)`). Суммарная write-цена выросла на 2.2% — это и есть ответ на
вопрос тикета.

## EXPLAIN

Планы на текущем объёме: `docs/night/logs/t291_explain_before.txt` /
`t291_explain_after.txt`. На 587 задачах планировщик **сознательно** оставляет
`Seq Scan` (таблица влезает в 27 страниц) — индексы не ломают план, но и не
выигрывают на этом объёме. Планы на 200k строк — в `t291_scale_200000.txt`
(см. таблицу выше): там `Seq Scan on work_tasks` уступает
`Bitmap Index Scan on ix_work_tasks_section_id_status`, а `Seq Scan on
route_stages` в EXISTS исчезает полностью.

## Проверки

- `alembic upgrade head` на изолированной `ktm2000_t291` — чисто;
- `alembic downgrade 077` → `upgrade head` — чисто (повторный проход безопасен,
  весь DDL с `if_not_exists`/`if_exists`, как в #290);
- `alembic heads` — один head `078_hot_path_indexes`;
- `alembic check` — `No new upgrade operations detected`;
- все 8 индексов видны в `pg_indexes`;
- `ruff check backend` — зелёный;
- `npm run test:pytest` (PYTEST_NUM_WORKERS=2) — см. отчёт оркестратора.

## Откат

`alembic downgrade 077_ready_transfer_indexes` — миграция обратима, `downgrade`
восстанавливает дропнутый `ix_stock_transactions_to_location_id`.
