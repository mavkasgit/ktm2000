# Backend — KTM-2000

FastAPI + SQLAlchemy async + Alembic. Python 3.12+.

## Структура

```
backend/app/
├── api/routes/     # Эндпоинты FastAPI
├── core/           # Config, database, deps
├── models/         # SQLAlchemy ORM
├── schemas/        # Pydantic
├── services/       # Бизнес-логика
├── stock/          # Stock Ledger (StockTransaction, StockBalance)
├── transfers/      # Передачи между участками
└── seeds/          # Демо-данные
```

## Правила

- Все операции с БД — через `AsyncSession` (async).
- Миграции: `npm run db:makemigrate -- "описание"` → `npm run db:migrate` (из корня).
- Seed: `npm run db:seed`.
- API docs: `http://localhost:8012/docs` (dev).

## Stock Ledger

Единый источник правды — `StockTransaction` (append-only). Legacy `SpgRemainder`, `Movement` удалены.

- `Transfer` → 2 транзакции (`TRANSFER_SEND` + `TRANSFER_RECEIVE`) через `StockCommandService.record()`.
- Отмена = компенсационная транзакция с `reverses_id` (журнал действий — `action_journal`, ADR-0019).
- Детали домена → [`docs/project-overview.md`](../docs/project-overview.md).

## Dev-режим

- `npm run backend` (из корня) поднимает `backend/scripts/dev_server.py`, а не
  `uvicorn --reload` напрямую. Скрипт нужен на Windows: uvicorn перезапускает
  рабочий процесс через `CTRL_C_EVENT`, который бьёт по всей консоли и уносит
  FRONTEND/DB из `npm run dev`. Там же — скоуп `app/` (правки `tests/`, `alembic`,
  `scripts` не перезапускают backend) и пропуск рестарта, если изменённый файл
  не компилируется: тогда backend продолжает работать на последней валидной
  версии кода.
- Источник правды для DSN — env-файл (`.env.dev`, `$ENV_FILE` для
  `.env.prod`/`.env.test`), а не переменная окружения `DATABASE_URL`.
  `app.core.env_file.apply_env_file(override=True)` грузит файл **поверх**
  окружения и вызывается до импорта приложения: `dev_server.py` и
  `alembic/env.py`. Тесты изолированы через `TEST_DATABASE_URL` и это не
  затрагивают. Прод-контейнер файла не содержит — там DSN задаёт compose.

## Тесты

Канон pytest → [`tests/AGENTS.md`](tests/AGENTS.md).