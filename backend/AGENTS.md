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
- API docs: `http://localhost:8010/docs` (dev).

## Stock Ledger

Единый источник правды — `StockTransaction` (append-only). Legacy `SpgRemainder`, `Movement` удалены.

- `Transfer` → 2 транзакции (`TRANSFER_SEND` + `TRANSFER_RECEIVE`) через `StockCommandService.record()`.
- Отмена = компенсационная транзакция с `compensates_tx_id`.
- Детали домена → [`docs/project-overview.md`](../docs/project-overview.md).

## Тесты

Канон pytest → [`tests/AGENTS.md`](tests/AGENTS.md).