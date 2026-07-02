# План рефакторинга KTM-2000: от SpgRemainder к Location-based Stock Ledger

> Источник: архитектурный диалог от 2026-07-03. План замкнут и утверждён.
> Ветка: `refactor/stock-ledger`. Точка невозврата — Этап 7.

---

## Старт-протокол для новой сессии

> Этот раздел — инструкция для агента, открывшего проект в свежей сессии.
> Выполнять строго в указанном порядке, без пропусков.

### Шаг 0. Контекст (обязательно первым делом)
1. Прочитать [`AGENTS.md`](file:///c:/Users/user/VibeCoding/ktm2000/agents.md) целиком —
   там стек, команды, принципы рефакторинга, запреты, глоссарий целевого домена.
2. Прочитать этот файл (`PLAN_stock_ledger.md`) целиком — особенно раздел
   «9. Прогресс», чтобы понять, на какой фазе мы сейчас.
3. Проверить текущую ветку: `git branch --show-current` — должна быть
   `refactor/stock-ledger`. Если нет — переключиться.
4. Проверить состояние миграций: `cd backend && python -c "from alembic.config
   import Config; from alembic import command; cfg=Config('alembic.ini');
   command.current(cfg)"` — ожидается `022_stock_ledger_core` или выше.

### Шаг 1. Исследование через субагентов (перед началом любой фазы)

**ВАЖНО: тесты пишет только субагент, не основной агент.** Основной агент
делает модель/сервисы/миграции, а тестирование делегирует explore/general
субагентам с чётким ТЗ.

Перед началом каждой новой фазы запускать параллельно explore-субагентов
(дешёвая модель `north-mini-code-free`) для актуального среза системы:

- **Перед Этапом 2 (Transfer migration)**: субагент изучает текущий
  `app/transfers/services.py` (особенно `transfer_send`, `cancel_transfer`,
  `correct_transfer`) и `app/models/transfer.py` — возвращает точные имена
  функций, их шаги, что пишут в Movement/SpgRemainder, где двойная запись
  будет вставлена.
- **Перед Этапом 3 (Shopfloor operations)**: субагент изучает
  `app/services/shopfloor/operations_tasks.py` (особенно каскад
  `return_remainder_to_stock → compensate_spg_remainders →
  trigger_auto_consume_for_spg_tasks → auto_consume_available_remainders →
  consume_remainder`) и `app/services/shopfloor/cache.py` — возвращает
  карту вызовов, какие функции помечаются deprecated.
- **Перед Этапом 4 (WorkTask cleanup)**: субагент изучает `app/models/work_task.py`
  и `app/services/shopfloor/cache.py::_refresh_task_cache` — возвращает
  все места чтения `cached_*` полей (backend + frontend).
- **Перед Этапом 5 (Quality migration)**: субагент изучает `app/models/defect.py`,
  `app/models/rework_task.py`, `app/defects/` — возвращает карту решений
  DefectDecision и где они должны создавать компенсационные StockTransaction.
- **Перед Этапом 6 (Frontend)**: субагент изучает `frontend/src/features/{sections,
  execution,transfers,spg}` и `frontend/src/shared/api/` — возвращает
  список компонентов и API-вызовов, затрагиваемых миграцией.

Формат ТЗ для субагента: «Изучи [конкретные файлы] — верни stруктурированный
markdown-отчёт: [список пунктов]. Не пиши код, только исследование.»

### Шаг 2. Выполнение фазы

1. Найти в разделе «3. Этапы» текущую (первую незавершённую) фазу.
2. Выполнить подпункты по порядку, отмечая `[x]` в чек-листе.
3. После каждого подпункта:
   - прогон `python -m pytest tests/<релевантный_файл> -v` в 4 воркера
   - прогон `python -m pytest tests/test_integrity_invariants.py -v`
   - если сломался baseline — откатить изменение
4. Тесты делегировать субагенту (pytest-writer скилл или general-агент с
   ТЗ по покрытию конкретной операции).
5. В конце фазы — коммит с `feat(stock): Этап N — <краткое описание>`.
6. Обновить раздел «9. Прогресс» — отметить фазу `[x]`.

### Шаг 3. Передача хождения пользователю

После завершения фазы (или если нужен архитектурный выбор по месту) —
краткий отчёт пользователю: что сделано, какие файлы, сколько тестов
проходит, и предложить следующую фазу или паузу.

---

## 0. Архитектурные принципы (фиксация)

1. **Ядро хранит факты, UI управляет политиками.** StockTransaction, WorkTask, StockBalance фиксируют произошедшее. Автопотребление, перевыполнение, переделка, автозакрытие — отдельные явные команды, инициируемые пользователем/настройкой, наблюдаемые в UI.
2. **Любая спорная механика должна быть видимой и тестируемой через UI** (чекбокс/режим + запись в журнале как отдельное действие), а не скрыта внутри домена.
3. **Баланс = projection из StockTransaction.** Никаких мутабельных остатков (SpgRemainder удаляется).
4. **Append-only ledger.** Отмена = компенсационная транзакция, не delete.
5. **Transfer остаётся бизнес-обёрткой** над парой StockTransaction.

## 1. Зафиксированные решения

| # | Решение | Итог |
|---|---|---|
| 1 | Стратегия миграции | Гибрид: ядро inventory (big-bang) + обвязка strangler |
| 2 | Transfer | Оставить бизнес-сущностью с lifecycle. Создаёт 2 StockTransaction. |
| 3 | Планирование | Не трогать (ProductionPlan/PlanPosition/InternalPlan/SectionPlanLine/ReleaseBatch остаётся) |
| 4 | Event model | Синхронные команды + `StockProjectionManager` (компромисс 1.5) |
| 5 | Качество | `QualityState` на StockTransaction (GOOD/SCRAP/REWORK/QUARANTINE) |
| 6 | Location | `Section → Location` расширением с `type` enum |
| 7 | Автопотребление | Отдельная явная бизнес-операция `issue_to_work(auto_consume=True/False)`. Все каскады убрать. UI: чекбокс + журнал. |
| 8 | completed_qty / scrap_qty | Хранить в WorkTask (мутабельный агрегат). Ledger — для аудита/сверки через инвариант-тесты. |
| 9 | Movements vs StockTransactions | Новые таблицы `stock_transactions`, `stock_balances`. `movements` → read-only архив → удалить. |
| 10 | API | Поднять `/api/v2/stock/*` рядом со старым `/api/spg/*`. Никаких `if legacy`. |

## 2. Целевая доменная модель

### Location (расширение `sections`)
```
sections (существующая таблица, не переименовываем)
  + type: LocationType enum (NEW)
     RAW_STOCK | WIP_STOCK | FINISHED_STOCK
     LASER | WELDING | PAINTING | ASSEMBLY
     SCRAP | QUARANTINE | TRANSIT
  + spg_id: FK storage_production_groups (nullable, для storage-локаций)
  - kind: deprecated, alias на type
```

### StockTransaction (новая таблица)
```
id, product_id, from_location_id, to_location_id (оба nullable для in/out),
quantity (>0), reason (Reason enum), quality_state (QualityState enum),
task_id, transfer_id, section_plan_line_id (nullable),
performed_at, accounted_at, created_at, created_by,
idempotency_key, source_ref, comment, is_post_factum
```

**Reason enum:**
`ISSUE_TO_WORK | COMPLETE | TRANSFER_SEND | TRANSFER_RECEIVE | RETURN_TO_STOCK | RETURN_TO_PREVIOUS | FINAL_RELEASE | SCRAP | REWORK | ADJUSTMENT_IN | ADJUSTMENT_OUT | MANUAL_IN | MANUAL_OUT`

**QualityState enum:** `GOOD | SCRAP | REWORK | QUARANTINE`

### StockBalance (projection, материализованный кэш)
```
id, product_id, location_id, quality_state,
balance_qty (Decimal, = SUM(in) - SUM(out) по ключу),
refreshed_at
```

### WorkTask (мутабельный агрегат)
```
planned_qty, completed_qty, scrap_qty (хранить, не projection),
status, route_stage_id, section_id (=location), product_id
- cached_*: deprecated → removed
```

### Transfer (остаётся, упрощается запись)
```
lifecycle: draft→sent→accepted→partially_accepted→rejected→cancelled
transfer_send → создаёт 2 StockTransaction (TRANSFER_SEND + TRANSFER_RECEIVE)
cancel/correct → компенсационные StockTransaction (не delete)
```

### Defect
```
business-запись-обоснование, + stock_transaction_id FK (nullable)
не источник правды
```

### StockProjectionManager (компромиссный event-слой)
```python
class StockProjectionManager:
    async def stock_changed(self, tx: StockTransaction):
        await self.refresh_balance(tx)         # StockBalance
        await self.refresh_task_projection(tx) # WorkTask.completed/scrap
        await self.refresh_spl_projection(tx)  # SectionPlanLine
        await self.refresh_quality_view(tx)    # опц. агрегат
```
Единая точка обновления всех проекций. Вызывается из `StockCommandService.record()` синхронно в рамках транзакции.

### StockCommandService — единственный путь записи
```python
class StockCommandService:
    async def record(self, cmd: StockCommand) -> StockTransaction:
        # валидация, idempotency, запись StockTransaction
        # await projection_manager.stock_changed(tx)
        return tx
```
Каскад `return_remainder → compensate → trigger_auto_consume → consume_remainder` **схлопывается в одну команду**.

---

## 3. Этапы

### Этап 0 — Подготовка (1-2 дня)
- [x] Ветка `refactor/stock-ledger`
- [ ] Бэкап БД (dev — через pg_dump при необходимости)
- [ ] Baseline: все ~4000 тестов проходят
- [x] Обновить `AGENTS.md`: целевая модель, глоссарий, принципы
- [x] Создать черновики новых инвариант-тестов (skip-режим)

### Этап 1 — Ядро inventory (big-bang, параллельная модель)
- [x] 1.1. Модели `app/stock/models.py`: Location (extend Section), StockTransaction, StockBalance, enums
- [x] 1.2. Alembic миграция `022_stock_ledger_core`:
  - `ALTER TABLE sections ADD COLUMN type LocationType`
  - data-migration: `type` по существующим `kind`/`spg.storage_kind`
  - `CREATE TABLE stock_transactions`, `stock_balances`
- [x] 1.3. `ProjectionManager` + `StockCommandService` в `app/stock/services.py`
- [x] 1.4. Тесты: `tests/stock/test_stock_command.py`
  - `record(ISSUE_TO_WORK, from=RAW_STOCK, to=LASER)` → balance[RAW_STOCK]-=q, balance[LASER]+=q
  - `record(SCRAP, from=PAINTING, to=SCRAP, quality=SCRAP)` → баланс по качеству
  - Идемпотентность по `idempotency_key`
  - Negative balance запрещён (кроме явно разрешённых post-factum)

> **Design refinement**: `quality_state` разобран на `from_quality_state` +
> `to_quality_state` — это позволяет описать переход GOOD→SCRAP/REWORK в одной
> транзакции. Баланс считается по ключу `(product, location, quality_state)`,
> где исходящая сторона уменьшает `from_quality_state`, входящая —
> увеличивает `to_quality_state`.

### Этап 2 — Transfer migration (strangler, двойная запись)
- [ ] 2.1. Adapter двойной записи в `transfer_send`:
  - Transfer + 3 Movement (старое) + 2 StockTransaction (новое) в одной транзакции
  - Расширенные инвариант-тесты: `stock_balance = movement_sums` для transfer
- [ ] 2.2. `cancel_transfer` → компенсационные StockTransaction
- [ ] 2.3. Новые read-API `/api/v2/stock/balance`, `/api/v2/stock/transactions`
- [ ] 2.4. Стабилизация, прогон всех тестов

### Этап 3 — Shopfloor operations (strangler, операция за операцией)
- [ ] 3.1. `issue_to_work` → `record(ISSUE_TO_WORK, auto_consume=True/False)` (двойная запись)
- [ ] 3.2. `complete_task` → `record(COMPLETE, quality=GOOD)` + для брака `record(SCRAP, quality=SCRAP)`
- [ ] 3.3. **Каскад return_remainder схлопывается**:
  - `return_remainder_to_stock` → одна команда `record(RETURN_TO_STOCK, from=location, to=RAW_STOCK)`
  - `compensate_spg_remainders` → **удалить**
  - `trigger_auto_consume_for_spg_tasks` → **убрать автоматический вызов**, оставить как явную опцию `issue_to_work(auto_consume=True)`
  - `consume_remainder` → `record(ISSUE_TO_WORK from RAW_STOCK)`
- [ ] 3.4. После стабилизации каждой операции — убрать двойную запись в Movement

### Этап 4 — WorkTask cleanup
- [ ] 4.1. `cached_*` пометить deprecated, переписать `_refresh_task_cache` на чтение из StockBalance/transactions
- [ ] 4.2. Расширить инвариант-тесты: `cached_* = SUM(stock_transactions WHERE reason=X)`
- [ ] 4.3. После миграции UI (Этап 6) — убрать `cached_*` колонки отдельной миграцией

### Этап 5 — Quality migration
- [ ] 5.1. Заполнить `quality_state=GOOD` для всех существующих transactions (data-migration)
- [ ] 5.2. `Defect` → добавить `stock_transaction_id` FK (nullable)
- [ ] 5.3. `DefectDecision`:
  - `scrap` → `record(SCRAP, to=SCRAP, quality=SCRAP)`
  - `rework_current` → `record(REWORK, to=REWORK, quality=REWORK)`
  - `return_previous` → `record(RETURN_TO_PREVIOUS)`
  - `hold` → `record(to=QUARANTINE, quality=QUARANTINE)`
- [ ] 5.4. `ReworkTask.complete` → `record(COMPLETE, from=REWORK, to=next, quality=GOOD)`

### Этап 6 — Frontend (strangler)
- [ ] 6.1. Новый API-слой `shared/api/stock.ts` (balance, transactions)
- [ ] 6.2. `features/sections/SpgRemaindersDialog` → `StockBalanceDialog`
- [ ] 6.3. `features/execution/RemainderAllocationDialog` → переписать на StockBalance
- [ ] 6.4. `features/transfers` → переключить на новый API
- [ ] 6.5. UI-точки спорных механик: чекбокс автопотребления, кнопки rework/scrap, индикатор перевыполнения
- [ ] 6.6. Убрать упоминания `SpgRemainder` с фронта

### Этап 7 — Cleanup (точка невозврата)
- [ ] 7.1. Удалить `SpgRemainder` модель + таблицу (после data-verification)
- [ ] 7.2. Удалить `Movement` модель + таблицу (`movements` → read-only архив → drop)
- [ ] 7.3. Удалить: `compensate_spg_remainders`, `trigger_auto_consume_for_spg_tasks`, `auto_consume_available_remainders`, `consume_remainder`, `restore_remainder`
- [ ] 7.4. Удалить старые `_make_*` хелперы, заменённые новыми
- [ ] 7.5. Обновить `AGENTS.md` (новая архитектура, инварианты, codegraph sync)

---

## 4. Явные UI-точки для спорных механик

Каждая спорная механика = отдельное действие + журнал:

- **Автопотребление**: чекбокс при выдаче + строка в журнале «Автопотребление N, источник: Склад X»
- **Перевыполнение**: «План 100, Факт 108, ⚠ +8%» + кнопка «Подтвердить»
- **Переделка**: отдельные действия «Перевести в REWORK» / «Вернуть из REWORK» / «Списать после REWORK»
- **QualityState**: переключатель GOOD/SCRAP/REWORK/QUARANTINE с подтверждением
- **Автозакрытие задач** (если будет): явный чекбокс + кнопка «Закрыть»

Через полгода любую из них можно убрать удалением чекбокса/кнопки без переписывания ядра.

---

## 5. Стратегия тестирования

- **Baseline gate**: на этапах 0-3 каждый PR не должен ломать ни один из ~4000 существующих тестов
- **Новые инвариант-тесты** в `test_integrity_invariants.py`:
  - `stock_balance = SUM(stock_transactions)` по ключу `(product, location, quality_state)`
  - `no orphan stock_transaction` (transfer_id/task_id валидны)
  - `transfer.balance = stock_transactions sums`
  - `worktask.completed_qty = SUM(stock_transactions WHERE reason=COMPLETE AND task_id=X)` ← свертка мутабельного поля (аудит)
- **Парные тесты** на этапе двойной записи: `movement_sums == stock_balance`
- **E2E**: `assert_no_invariants_violations(session, context=...)` после каждой команды
- Каждый этап заканчивается прогоном `npm run test:pytest` в 4 воркера

---

## 6. Риски и откат

| Риск | Митигация |
|---|---|
| Рассинхрон при двойной записи (Этап 2-3) | Расширенные инвариант-тесты + alerting |
| Производительность projection refresh | Batch-refresh, индексы на `(product_id, location_id, quality_state)` |
| Фронтенд ломается при изменении API | Версионирование `/api/v2/stock/*`, старый `/api/spg/*` live до Этапа 7 |
| Migration data-loss | Каждый ALTER через Alembic с downgrade, бэкап перед этапами 1, 5, 7 |
| Слишком долго | Этапы 1-3 можно паузить между, система остаётся в рабочем состоянии |

**Точка невозврата**: Этап 7. До него можно откатиться к старой логике.

---

## 7. Объём работ (оценка)

| Этап | Сроки | Изменяемые файлы |
|---|---|---|
| 0. Подготовка | 1-2 дня | AGENTS.md, тестовый baseline |
| 1. Ядро inventory | 3-5 дней | новые `app/stock/`, 1 миграция, ~30 новых тестов |
| 2. Transfer migration | 4-6 дней | `app/transfers/services.py`, инвариант-тесты |
| 3. Shopfloor operations | 6-10 дней | `app/services/shopfloor/operations_tasks.py`, cascade removal |
| 4. WorkTask cleanup | 3-5 дней | `app/services/shopfloor/cache.py`, модели |
| 5. Quality migration | 4-6 дней | `app/defects/`, `app/rework/`, models |
| 6. Frontend | 5-8 дней | `features/{sections,execution,transfers,spg}` |
| 7. Cleanup | 2-3 дня | удаление старого кода, миграции |
| **Итого** | **~4-6 недель** | |

---

## 8. Использование субагентов при выполнении

- **Этап 1 (ядро)** — выполнить сам (architectural decisions) + explore-агенты для валидации
- **Этапы 2-6** — execution-субагенты по чётким ТЗ (одна операция = один субагент), ревью + прогон тестов
- **Этап 7** — сам с проверкой инвариантов

---

## 9. Прогресс

- [x] Этап 0 — Подготовка
- [x] Этап 1 — Ядро inventory
- [ ] Этап 2 — Transfer migration
- [ ] Этап 3 — Shopfloor operations
- [ ] Этап 4 — WorkTask cleanup
- [ ] Этап 5 — Quality migration
- [ ] Этап 6 — Frontend
- [ ] Этап 7 — Cleanup
