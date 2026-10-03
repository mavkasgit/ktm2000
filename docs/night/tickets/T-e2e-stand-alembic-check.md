# T — `alembic check` на e2e-стенде врал из-за служебной `e2e_stand_stamp`

Срез: `night/2026-10-03-a`, worktree `C:/Users/LogoPrint/VibeCoding/ktm2000-night-a`.
Источник: PLAYBOOK §10.7 п.2. Тикета нет — правка инфраструктурная, отдельный коммит.

## Воспроизведение (до правки)

БД стенда: `ktm2000_e2e_nighta` (свой namespace, `E2E_ENV_FILE=.env.e2e.night-a.local`),
интерпретатор `backend/.venv/Scripts/python.exe` основного дерева.

```
$ cd backend && ENV_FILE=../.env.e2e.night-a.local \
    "C:/.../backend/.venv/Scripts/python.exe" -m alembic check
INFO  [alembic.autogenerate.compare.tables] Detected removed table 'e2e_stand_stamp'
ERROR [alembic.util.messaging] New upgrade operations detected: [('remove_table',
  Table('e2e_stand_stamp', MetaData(), Column('key', TEXT(), ...), ...))]
FAILED: New upgrade operations detected: [('remove_table', ...)]
```

## Механика

`e2e_stand_stamp` создаёт **сам стенд**, а не продукт:

- `scripts/e2e-db.py:141` — `STAMP_TABLE = "e2e_stand_stamp"`;
- `scripts/e2e-db.py:330 _write_stamp` — `CREATE TABLE IF NOT EXISTS e2e_stand_stamp
  (key text PRIMARY KEY, value text NOT NULL, updated_at timestamptz DEFAULT now())`,
  сырым SQL через asyncpg, мимо Alembic;
- `_stamp_stand` вызывает её сразу после пересоздания БД стенда — таблица штампуется
  версией репозитория и digest'ом правил маршрута, по которым `ensure` решает, что стенд
  устарел.

В моделях она не описана: `grep -rn "e2e_stand_stamp" backend/app/` → пусто (это проверено,
`backend/app/models/**` не трогал). Поэтому autogenerate видел в БД стенда таблицу, которой
нет в `Base.metadata`, и предлагал `remove_table` — то есть врал: «есть незамигрированные
изменения», которых нет.

## Решение

Ровно тот же механизм, что уже есть в репозитории для служебных таблиц шагов пересчёта
(тикет #261, `MIGRATION_HELPER_TABLES` в `alembic/env.py`): исключение на уровне
`include_object`, без модели и без удаления таблицы. Это не костыль — в проекте это
канонический способ объявить «эту таблицу создаёт не Alembic».

`backend/alembic/env.py`:

```python
STAND_SERVICE_TABLES = frozenset({"e2e_stand_stamp"})

def include_object(object, name, type_, reflected, compare_to):
    ignored_tables = MIGRATION_HELPER_TABLES | STAND_SERVICE_TABLES
    return not (type_ == "table" and (name == "alembic_version" or name in ignored_tables))
```

Ни `scripts/e2e-db.py`, ни модели не менялись.

## Приёмка

| Проверка | Результат |
|---|---|
| `alembic check` на стенде (`ktm2000_e2e_nighta`) после правки | `No new upgrade operations detected.` — код возврата 0 |
| Реальное расхождение всё ещё ловится | добавлен обратимый `ALTER TABLE sections ADD COLUMN t308_probe integer` → `Detected removed column 'sections.t308_probe'` + `FAILED: New upgrade operations detected: [('remove_column', ...)]`. Колонка убрана, повторный `check` снова `No new upgrade operations detected.` |
| `alembic check` на dev-БД | **не выполнялся**: `.env.dev` — контейнерная конфигурация (`STORAGE_ROOT=/app/storage`), процесс на хосте падает в `Settings` (ADR-0026). По указанию оркестратора добиваться зелёного на dev-БД не нужно; расхождений с этой правкой dev-БД не касается — исключён ровно один ненайденный в моделях ненайденный объект |
| `cd backend && ruff check .` | `All checks passed!` |
| `npm run test:pytest -- tests/test_migrations.py -q` | `17 passed in 147.59s` |

## Что НЕ сделано

- `backend/app/models/**`, `backend/app/services/**`, `backend/app/seeds/**`,
  `backend/app/api/routes/**`, `frontend/src/**` — чужие зоны, не трогал.
- `scripts/e2e-db.py` править не потребовалось.
- Dev-БД не мигрировал и не проверял (см. выше).
- Полный `npm run test:pytest` не гонял: правка касается только `alembic/env.py`
  (сборочная конфигурация миграций), релевантный набор `tests/test_migrations.py` зелёный.
