# AGENTS.md

Этот файл содержит контекст проекта, стандарты разработки и инструкции для ИИ-агентов. Прочитайте этот файл перед началом работы, чтобы не тратить лишние токены на исследование структуры проекта.

## Кодграф (CodeGraph)

В проекте настроен и используется локальный индекс **CodeGraph** от `colbymchenry/codegraph`. 

> [!IMPORTANT]
> **НЕ сканируйте директории с помощью `list_dir` или `grep_search` для поиска классов, функций или взаимосвязей в коде.** 
> Вместо этого используйте подключенный MCP-сервер CodeGraph или запускайте CLI-команды CodeGraph для быстрого и дешевого поиска по графу зависимостей.

### Ключевые команды CodeGraph:
- Показать статус индекса: `npx @colbymchenry/codegraph status`
- Найти символ или файл: `npx @colbymchenry/codegraph query <имя_символа>`
- Найти все вызовы функции/метода: `npx @colbymchenry/codegraph callers <имя_метода>`
- Найти все вызываемые методом функции: `npx @colbymchenry/codegraph callees <имя_метода>`
- Анализ влияния изменений символа: `npx @colbymchenry/codegraph impact <имя_символа>`
- Обновить/синхронизировать индекс после изменений: `npx @colbymchenry/codegraph sync`

---

## Контекст проекта

**KTM-2000** — это локальная система производственного планирования и контроля для цехового производства.

### Стек технологий:
- **Backend:** Python 3.12+, FastAPI, SQLAlchemy (асинхронный клиент `asyncpg`), Alembic, pytest.
- **Frontend:** React 19+, Vite, Tailwind CSS, shadcn/ui, TanStack Table. Кодовая база фронтенда структурирована по методологии **Feature-Sliced Design (FSD)**.
- **База данных:** PostgreSQL 15 (в Docker).

---

## Команды разработки

### Запуск окружения (dev):
```bash
npm run dev
```
*(Команда поднимает Postgres в Docker, применяет миграции Alembic и запускает локально backend на `:8010` и frontend на `:5180`)*

### Миграции базы данных:
- Создать автомиграцию: `npm run db:makemigrate -- "описание изменений"` (выполнять из корня)
- Применить миграции: `npm run db:migrate` (выполнять из корня)

### Тестирование:
- Запуск всех тестов: `npm run test:pytest` (из корня)
- Ускоренный параллельный запуск тестов в 4 воркера (требуется `pytest-xdist`):
  ```bash
  cd backend && python -m pytest tests/ -v -n 4
  ```
- Запуск конкретного теста:
  ```bash
  cd backend && python -m pytest tests/test_shopfloor_api.py::test_shopfloor_over_issue_rejected -v
  ```

---

## Стандарты и правила кодирования

1. **Edge Cases (Крайние случаи):** Всегда детально прорабатывайте обработку ошибок, валидацию входных данных и крайние случаи. Не оставляйте placeholders.
2. **Асинхронность в бэкенде:** Все операции с БД в FastAPI должны использовать асинхронные сессии (`AsyncSession`).
3. **Методология FSD на фронтенде:** Четко следуйте структуре слоев: `app`, `pages` (если применимо), `features`, `entities`, `shared`. Не допускайте перекрестных импортов между слайсами одного слоя (например, feature не должна импортировать другую feature).
4. **Коммиты:** Используйте осмысленные conventional commit сообщения на русском языке (например, `feat: добавить валидацию...`, `fix: исправить ошибку...`).
5. **Сохранение документации:** Сохраняйте существующие docstring-комментарии в коде, если они не мешают изменениям.
6. **Кликабельные ссылки:** При ответе пользователю всегда давайте кликабельные markdown-ссылки на изменяемые или важные файлы, используя протокол `file://` (например, `[main.py](file:///c:/Users/user/VibeCoding/ktm2000/backend/app/main.py)`).

### Целостность данных Transfer ↔ Movement

В системе два слоя хранят один и тот же факт перемещения:
- `transfers` — бизнес-сущность с жизненным циклом (`status`, `cancel`, `correct`)
- `movements` — append-only ledger; `transfer_send` + `transfer_receive` пишутся атомарно в [`transfer_send`](file:///c:/Users/user/VibeCoding/ktm2000/backend/app/transfers/services.py)
- `WorkTask.cached_*` пересчитывается из `SUM(Movement)` в [`_refresh_task_cache`](file:///c:/Users/user/VibeCoding/ktm2000/backend/app/services/shopfloor/cache.py)

Чтобы ловить рассинхрон этих проекций, в [`tests/test_integrity_invariants.py`](file:///c:/Users/user/VibeCoding/ktm2000/backend/tests/test_integrity_invariants.py) есть хелпер:

```python
from tests.test_integrity_invariants import assert_no_invariants_violations
await assert_no_invariants_violations(session, context="after-cancel")
```

Он выполняет 7 SQL-проверок (movement↔transfer, transfer↔movement, cancel-чистота, cached↔SUM, transfer↔sum, line↔task). Вызывайте его в своих e2e-тестах в ключевых точках (после take-to-work, issue, complete, transfer, cancel) — это поймает регрессию, если кто-то забудет обновить один из слоёв при рефакторинге.

---

## Рефакторинг Stock Ledger (в ветке `refactor/stock-ledger`)

Подробный план: [`PLAN_stock_ledger.md`](file:///c:/Users/user/VibeCoding/ktm2000/PLAN_stock_ledger.md). Ниже — короткий глоссарий и принципы, обязательные для любого кода в этой ветке.

### Архитектурные принципы

1. **Ядро хранит факты, UI управляет политиками.** `StockTransaction`, `WorkTask`, `StockBalance` фиксируют произошедшее. Автопотребление, перевыполнение, переделка, автозакрытие — отдельные явные команды, инициируемые пользователем/настройкой, наблюдаемые в UI (чекбокс + журнал). Не прятать спорную механику внутрь домена.
2. **Баланс = projection из StockTransaction.** Никаких мутабельных остатков (SpgRemainder удаляется на Этапе 7).
3. **Append-only ledger.** Отмена = компенсационная транзакция, не `delete`.
4. **Transfer остаётся бизнес-обёрткой** над парой StockTransaction (TRANSFER_SEND + TRANSFER_RECEIVE).
5. **API v2**: `/api/v2/stock/*` рядом со старым `/api/spg/*`. Никаких `if legacy`, флагов, костылей.

### Целевой домен (после Этапа 7)

| Сущность | Таблица | Назначение |
|---|---|---|
| `Location` | `sections` (расшир.) | Где находится материал; `type: LocationType` enum (RAW_STOCK/WIP_STOCK/FINISHED_STOCK/LASER/WELDING/PAINTING/ASSEMBLY/SCRAP/QUARANTINE/TRANSIT) |
| `StockTransaction` | `stock_transactions` (new) | Единый append-only ledger: `from_location_id`, `to_location_id`, `quantity`, `reason`, `from_quality_state`, `to_quality_state` (для переходов GOOD→SCRAP/REWORK), `task_id`, `transfer_id` |
| `StockBalance` | `stock_balances` (new) | Материализованный кэш баланса по `(product, location, quality_state)` |
| `WorkTask` | `work_tasks` | Мутабельный агрегат: `planned_qty`, `completed_qty`, `scrap_qty` хранятся (не projection). `cached_*` удалены |
| `Transfer` | `transfers` | Бизнес-lifecycle, создаёт 2 StockTransaction, cancel/correct = компенсации |
| `Defect` | `defects` | Бизнес-запись-обоснование, `stock_transaction_id` FK. Не источник правды |

**Enums:**
- `Reason`: `ISSUE_TO_WORK | COMPLETE | TRANSFER_SEND | TRANSFER_RECEIVE | RETURN_TO_STOCK | RETURN_TO_PREVIOUS | FINAL_RELEASE | SCRAP | REWORK | ADJUSTMENT_IN | ADJUSTMENT_OUT | MANUAL_IN | MANUAL_OUT`
- `QualityState`: `GOOD | SCRAP | REWORK | QUARANTINE`

### Запреты в ветке `refactor/stock-ledger`

- НЕ добавлять новые вызовы `compensate_spg_remainders`, `trigger_auto_consume_for_spg_tasks`, `auto_consume_available_remainders`, `consume_remainder`, `restore_remainder` — эти функции помечены в deprecated и будут удалены на Этапе 7.
- НЕ добавлять новые мутабельные остатки (по аналогии с `SpgRemainder`).
- НЕ прятать автопотребление/перевыполнение/переделку внутрь сервисов — только как явный параметр команды (`issue_to_work(auto_consume=True/False)`) с UI-чейндж-логом.
- НЕ ломать `/api/spg/*` и `/api/v1/*` до Этапа 7 — миграция идёт через `/api/v2/stock/*`.

### Состояние миграции

Смотрите раздел «9. Прогресс» в [`PLAN_stock_ledger.md`](file:///c:/Users/user/VibeCoding/ktm2000/PLAN_stock_ledger.md). На каждой фазе:
- двойная запись (Movement + StockTransaction) — пока оба источника живы;
- расширенные инвариант-тесты ловят рассинхрон: `stock_balance = SUM(stock_transactions)`, `worktask.completed_qty = SUM(stock_transactions WHERE reason=COMPLETE AND task_id=X)`;
- baseline-гейт: ~4000 существующих тестов не должны падать на этапах 0-3.
