# BASELINE — KTM-2000, ночь 2026-09-30

## Условия замеров

| Параметр | Значение |
|---|---|
| Рабочее дерево ночи | `C:/Users/LogoPrint/VibeCoding/ktm2000-night` (git worktree) |
| Ветка ночи | `night/2026-09-30-work` (база `0ac0228`) |
| Ветка человека | `night/2026-09-30` — **не трогается** |
| Основное дерево | `C:/Users/LogoPrint/VibeCoding/ktm2000` — живая работа человека, только чтение |
| Нагрузка при замерах | dev-стек активен (vite `:5172`, backend `:8012`, Postgres `:5440`/`:5441`) + **шёл прогон e2e человека** (артефакты `frontend/test-results/` обновлялись в 23:41) → все замеры помечены **«под нагрузкой»** |
| Воркеров xdist | `PYTEST_NUM_WORKERS=4` |

## Интерпретатор: расхождение с проектом (зафиксировано)

`AGENTS.md` называет окружением проекта `.venv`, в дереве реально есть
`backend/.venv`. Факты:

- `backend/.venv/pyvenv.cfg`: **Python 3.14.0**, `include-system-site-packages = false`.
- В `backend/.venv/Scripts/` нет ни `pytest.exe`, ни `uvicorn.exe` — пакеты
  тестового стека не установлены.
- Проект декларирует Python 3.12 (`AGENTS.md`: «Python 3.12 / FastAPI / SQLAlchemy async»).
- Фактически рабочий тестовый стек живёт в **системном** Python
  `C:\Users\LogoPrint\AppData\Local\Programs\Python\Python312\python.exe` — 3.12.10,
  `pytest 9.1.1`, `pytest-xdist`, `pytest-testmon`, `fastapi 0.142.2`,
  `sqlalchemy`, `asyncpg`, `alembic`, `httpx`. Launcher `scripts/test-run.ps1`
  вызывает просто `python -m pytest`, то есть берёт интерпретатор из `PATH`.

**Итог:** ночные замеры идут на системном Python 3.12.10 — иначе тесты не
запускаются (в `backend/.venv` нет зависимостей). Ничего в `.venv` не
устанавливалось: `AGENTS.md` прямо запрещает агенту установку зависимостей.
Расхождение «декларируем 3.12-venv, работаем на системном 3.12, а в дереве
лежит пустой 3.14-venv» — кандидат в BACKLOG (повторяемость окружения,
решение человека).

## Размер набора

- 186 тест-файлов, ~70 491 строк в `backend/tests/**/*.py`, один `conftest.py`.
- Канон параллельного прогона: `npm run test:pytest` (~3 мин по
  `backend/tests/AGENTS.md`).

## Прогоны

`wall` — время pytest из его же отчёта (`in 384.37s`), `shell` — время
обёртки `npm run` вместе с созданием/дропом run-DB.

| # | wall (pytest) | shell | Условия | Результат |
|---|---|---|---|---|
| 1 | 384.37s | 395s | **под нагрузкой**: dev-стек + прогон e2e человека | `1 failed, 1941 passed, 45 warnings` |
| 2 | 357.27s | 365s | dev-стек активен, e2e нет | `1 failed, 1941 passed, 45 warnings` |
| 3 | 355.27s | 363s | dev-стек активен, e2e нет | `1 failed, 1941 passed, 45 warnings` |
| **медиана (1–3)** | **357.27s** | 365s | — | — |
| **разброс** | 355.3–384.4s (±4%) | — | нагрузка даёт ~+8% | — |

Серия повторов (5 прогонов) на стабильность/flaky: `logs/flaky-1..5.log`,
результаты — в разделе ниже.

### Падения

Во всех трёх прогонах — **одно и то же** падение:

```
FAILED tests/test_e2e_stand.py::test_stand_database_is_not_the_dev_database
FileNotFoundError: .../ktm2000-night/.env.dev
```

Это **pre-existing** падение и артефакт окружения, а не дефект продукта:
тест читает локальный (gitignored) `.env.dev`, а в worktree/чистом клоне его
нет по определению. Сетап проекта (`docs/GETTING_STARTED.md:29`) —
`cp .env.example .env.dev`; в этом репозитории такой файл есть только в
основном дереве человека. Разбор и решение — тикет `T-0004`.

### Предупреждения (45)

| Источник | Кол-во | Зона |
|---|---|---|
| Pydantic deprecation (`app/core/config.py:107,112`, `app/schemas/*`, `app/api/routes/*`, `app/stock/api.py`) | 40 | продуктовая — ночному агенту запрещена |
| `@pytest.mark.asyncio` на синхронном тесте (`test_plan_endpoints_auth.py`, `test_stock_remainder_import.py`) | 2 | тестовая — тикет `T-0002` |
| `HTTP_422_UNPROCESSABLE_ENTITY` deprecated | 1 | вне тестов (`grep` по `tests/` пуст) |
| SQLAlchemy `fully NULL primary key identity` | 1 | источник в тестах не найден (шум) |

## Наблюдение по уборке БД

Убитый вручную прогон (в основном дереве, до переезда в worktree) оставил
run-DB `ktm2000_test_e2692385d4dc`, и `python scripts/test-db.py drop <name>`
её **не удалил**: `Skip drop ...: no matching owner row`. То есть БД
прерванного прогона живёт до TTL-уборки (`npm run test:db:cleanup`, 24h).
Кандидат в BACKLOG (диагностика/гигиена).
