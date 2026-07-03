# AGENTS.md

Этот файл содержит контекст проекта, стандарты разработки и инструкции для ИИ-агентов. Прочитайте этот файл перед началом работы, чтобы не тратить лишние токены на исследование структуры проекта.

## Архитектура оркестрации (ОБЯЗАТЕЛЬНО)

> [!IMPORTANT]
> Проект использует плагин **[oh-my-opencode-slim](https://github.com/alvinunreal/oh-my-opencode-slim)** с пресетом `opencode-go`. Все задачи выполняются через систему субагентов плагина. Конфиг: [`oh-my-opencode-slim.json`](file:///C:/Users/user/AppData/Roaming/orca/opencode-hooks/shared/oh-my-opencode-slim.json).

### Роли агентов

| Агент | Назначение |
|---|---|
| `orchestrator` | Оркестратор: планирует задачу, делегирует специалистам, ревьюит, правит план. **Не пишет код напрямую.** |
| `oracle` | Архитектурный совет, code review, отладка последнего рубежа. |
| `council` | Консультации: запускает несколько моделей параллельно, синтезирует ответ. |
| `fixer` | Execution: пишет/правит код, запускает тесты, применяет миграции. |
| `explorer` | Research: ищет символы, зависимости, риски через CodeGraph. |
| `librarian` | Внешние знания: документация, примеры, поиск по вебу. |
| `designer` | UI/UX: визуальная реализация, фронтенд-компоненты, дизайн-система. |
| `observer` | Анализ изображений, скриншотов, PDF. |

Модели для каждого агента настраиваются в плагине: [`oh-my-opencode-slim.json`](file:///C:/Users/user/AppData/Roaming/orca/opencode-hooks/shared/oh-my-opencode-slim.json). Не дублируйте их здесь.

Для настройки плагина (смена моделей, пресетов, диагностика) используйте скилл `oh-my-opencode-slim`.

### Обязательный рабочий процесс

1. **Исследование → `explorer`**: оркестратор делегирует разведку кодовой базы агенту `explorer` ДО составления плана.
2. **План → `orchestrator`**: на основе отчёта `explorer` оркестратор составляет пошаговый план.
3. **Реализация → `fixer`**: оркестратор делегирует имплементацию агенту `fixer` с детальным планом. Параллельные независимые части — запускайте несколькими `fixer`-агентами параллельно.
4. **Ревью → `orchestrator`**: оркестратор ревьюит результат, при необходимости запускает `explorer` для lookup или повторный `fixer` для правок. Сложные архитектурные вопросы → `oracle`.
5. **Проверка**: `fixer` запускает тесты (`npm run test:pytest`) и lint/typecheck. Отчёт возвращается оркестратору.

### Правила делегирования

- **Запрещено** оркестратору писать/редактировать код приложения самостоятельно (допускаются только правки в мета-файлы).
- **Запрещено** `fixer` выходить за рамки плана: добавлять фичи, не описанные в задании.
- **Запрещено** `fixer` делать git-коммиты — только редактирование и проверки.
- **Обязательно** запускать независимые подзадачи параллельно для экономии времени.
- **Обязательно** для поиска по коду использовать CodeGraph (см. раздел ниже), а не `grep`/`list_dir` — это касается и `explorer`, и `fixer`.
- После значимых изменений в коде `fixer` должен запустить `npx @colbymchenry/codegraph sync` для обновления индекса.

### Когда НЕ использовать субагентов

- Ответ на прямой вопрос пользователя о коде (lookup одного символа/файла) — можно ответить напрямую.
- Правка мета-файлов (`AGENTS.md`, `PLAN*.md`, `.opencode/*`, `README.md`).
- Команда git (commit, branch) — выполняется оркестратором по явному запросу пользователя.

---

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

### Целостность данных Transfer ↔ StockTransaction

Transfer создаёт 2 StockTransaction (`TRANSFER_SEND` + `TRANSFER_RECEIVE`) через `StockCommandService.record()`. Компенсации (cancel/correct) пишут компенсационные транзакции с `compensates_tx_id`.

Для проверки целостности в [`tests/test_integrity_invariants.py`](file:///c:/Users/user/VibeCoding/ktm2000/backend/tests/test_integrity_invariants.py) есть хелпер:

```python
from tests.test_integrity_invariants import assert_no_invariants_violations
await assert_no_invariants_violations(session, context="after-cancel")
```

Он выполняет 6 SQL-проверок (S1-S6) над StockTransaction/StockBalance: баланс = SUM(транзакций), нет orphan-транзакций, transfer.sent_qty = SUM(TRANSFER_SEND).

---

## Рефакторинг Stock Ledger (ЗАВЕРШЁН)

Рефакторинг в ветке `refactor/stock-ledger` полностью выполнен (Этапы 0-7).
Все legacy модели (SpgRemainder, Movement) и таблицы удалены.
Единый источник правды — `StockTransaction`.

Подробный план: [`PLAN_stock_ledger.md`](file:///c:/Users/user/VibeCoding/ktm2000/PLAN_stock_ledger.md) (исторический документ).

### Текущий домен

| Сущность | Таблица | Назначение |
|---|---|---|
| `Location` | `sections` (расшир.) | Где находится материал; `type: LocationType` enum (RAW_STOCK/WIP_STOCK/FINISHED_STOCK/LASER/WELDING/PAINTING/ASSEMBLY/SCRAP/QUARANTINE/TRANSIT) |
| `StockTransaction` | `stock_transactions` | Единый append-only ledger: `from_location_id`, `to_location_id`, `quantity`, `reason`, `from_quality_state`, `to_quality_state`, `task_id`, `transfer_id` |
| `StockBalance` | `stock_balances` | Материализованный кэш баланса по `(product, location, quality_state)` |
| `WorkTask` | `work_tasks` | Мутабельный агрегат: `planned_qty`, `completed_qty`, `scrap_qty` хранятся (не projection). `cached_*` удалены |
| `Transfer` | `transfers` | Бизнес-lifecycle, создаёт 2 StockTransaction, cancel/correct = компенсации |
| `Defect` | `defects` | Бизнес-запись-обоснование, `stock_transaction_id` FK. Не источник правды |

**Enums:**
- `Reason`: `ISSUE_TO_WORK | COMPLETE | TRANSFER_SEND | TRANSFER_RECEIVE | RETURN_TO_STOCK | RETURN_TO_PREVIOUS | FINAL_RELEASE | SCRAP | REWORK | ADJUSTMENT_IN | ADJUSTMENT_OUT | MANUAL_IN | MANUAL_OUT`
- `QualityState`: `GOOD | SCRAP | REWORK | QUARANTINE`

### Архитектурные принципы

1. **Ядро хранит факты, UI управляет политиками.** `StockTransaction`, `WorkTask`, `StockBalance` фиксируют произошедшее. Автопотребление, перевыполнение, переделка, автозакрытие — отдельные явные команды.
2. **Баланс = projection из StockTransaction.** Никаких мутабельных остатков.
3. **Append-only ledger.** Отмена = компенсационная транзакция, не `delete`.
4. **Transfer остаётся бизнес-обёрткой** над парой StockTransaction (TRANSFER_SEND + TRANSFER_RECEIVE).
5. **API v2**: `/api/v2/stock/*` рядом со старым `/api/spg/*`.
