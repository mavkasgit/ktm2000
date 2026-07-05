# AGENTS.md

Этот файл содержит контекст проекта, стандарты разработки и инструкции для ИИ-агентов. Прочитайте этот файл перед началом работы, чтобы не тратить лишние токены на исследование структуры проекта.

## Архитектура оркестрации и использование субагентов

Задачи в проекте выполняются по принципу разделения труда между главным агентом (оркестратором) и специализированными субагентами (руками) с изолированным контекстом.

### Общие принципы оркестрации:

1. **Оркестратор (главный сеанс)**:
   * Отвечает за планирование, принятие архитектурных решений, составление детальных спек (планов реализации), финальный контроль качества и ревью.
   * **Не пишет код приложения напрямую** (допускается только правка мета-файлов, планов и документации).
   * Диспатчит изолированные задачи субагентам.

2. **Субагенты (изолированные сеансы)**:
   * **Исследователь / Скаут (Research)**: выполняет разведку кодовой базы, поиск взаимосвязей и сбор фактов с точными координатами (файлы, строки). Ничего не меняет в кодовой базе.
   * **Исполнитель (Fixer / Executor)**: пишет и правит код строго в рамках плана/спеки, запускает тесты и обновляет индекс CodeGraph. Не должен отклоняться от плана или добавлять стороннюю логику.
   * **Верификатор (Verifier)**: запускается в чистом контексте исключительно для проверки критериев Definition of Done (DoD) и запуска тестов. Не пишет код.

### Обязательный рабочий процесс:

1. **Разведка**: Исследователь ищет факты, координаты и зависимости.
2. **Составление плана**: Оркестратор на основе отчета исследователя пишет пошаговую спеку.
3. **Реализация**: Оркестратор делегирует код исполнителю. Независимые параллельные ветки задач могут запускаться несколькими исполнителями одновременно.
4. **Верификация**: Верификатор прогоняет тесты и проверяет соответствие DoD.
5. **Ревью**: Оркестратор принимает работу или отправляет её на доработку.

### Правила делегирования и ограничения:
* Исполнителю запрещено делать коммиты без явного требования оркестратора.
* Для поиска по коду всегда следует использовать CodeGraph, а не сканировать каталоги с помощью `list_dir` или `grep_search`.
* После изменения кода исполнитель должен запустить ресинхронизацию индекса: `npx @colbymchenry/codegraph sync`.
* Простые вопросы, lookup одного символа, правка документации/планов или Git-команды могут выполняться оркестратором напрямую в главном сеансе без вызова субагентов.

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
- Ускоренный параллельный запуск всех тестов (рекомендуется): `npm run test:pytest:fast`
- Запуск тестов только для измененного кода: `npm run test:pytest:mon`
- Запуск только упавших тестов (last failed): `npm run test:pytest:lf`
- Медленный запуск всех тестов в один поток: `npm run test:pytest`
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
| `Location` (= `Section`) | `sections` | Где находится материал; `type: String(20)` — единый классификатор, 6 значений: `production`, `raw_stock`, `wip_stock`, `finished_stock`, `scrap`, `quarantine`. Enum `LocationType` и поле `kind` удалены в эпике `section-cleanup` (миграция 027). |
| `StockTransaction` | `stock_transactions` | Единый append-only ledger: `from_location_id`, `to_location_id`, `quantity`, `reason`, `from_quality_state`, `to_quality_state`, `task_id`, `transfer_id` |
| `StockBalance` | `stock_balances` | Материализованный кэш баланса по `(product, location, quality_state)` |
| `WorkTask` | `work_tasks` | Мутабельный агрегат: хранит планируемое количество в `planned_quantity` (не projection). Выполненное и забракованное количество вычисляются динамически на основе транзакций (`StockTransaction`). `cached_*` удалены |
| `Transfer` | `transfers` | Бизнес-lifecycle, создаёт 2 StockTransaction, cancel/correct = компенсации |
| `Defect` | `defects` | Бизнес-запись-обоснование, `stock_transaction_id` FK. Не источник правды |

**Enums:**
- `Reason`: `ISSUE_TO_WORK | COMPLETE | TRANSFER_SEND | TRANSFER_RECEIVE | RETURN_TO_STOCK | RETURN_TO_PREVIOUS | FINAL_RELEASE | SCRAP | REWORK | ADJUSTMENT_IN | ADJUSTMENT_OUT | MANUAL_IN | MANUAL_OUT`
- `QualityState`: `GOOD | SCRAP | REWORK | FINAL_SCRAP`

### Архитектурные принципы

1. **Ядро хранит факты, UI управляет политиками.** `StockTransaction`, `WorkTask`, `StockBalance` фиксируют произошедшее. Автопотребление, перевыполнение, переделка, автозакрытие — отдельные явные команды.
2. **Баланс = projection из StockTransaction.** Никаких мутабельных остатков.
3. **Append-only ledger.** Отмена = компенсационная транзакция, не `delete`.
4. **Transfer остаётся бизнес-обёрткой** над парой StockTransaction (TRANSFER_SEND + TRANSFER_RECEIVE).
5. **API**: `/api/stock/*` рядом со старым `/api/spg/*`.
