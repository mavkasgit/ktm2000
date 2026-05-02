# 07. Infrastructure and QA

## Local deployment

MVP должен запускаться локально:

```bash
npm run dev
```

Структура окружений повторяет HRMS:

- `infra/docker-compose.dev.yml`;
- `infra/docker-compose.test.yml`;
- `infra/docker-compose.prod.yml`;
- `.env.dev`;
- `.env.test`;
- `.env.prod`;
- root `package.json` scripts.

Сервисы:

- `frontend`;
- `backend`;
- `postgres`;
- `nginx`.

`redis` и `worker` не обязательны для MVP. Их нужно добавить позже, если импорт, отчеты или пересчет кешей станут долгими фоновыми задачами.

## Volumes

- PostgreSQL data volume;
- uploads volume для оригинальных Excel-файлов;
- backups volume.

## Environment variables

- `DATABASE_URL`;
- `SECRET_KEY`;
- `UPLOAD_DIR`;
- `BACKUPS_PATH`;
- `POSTGRES_CONTAINER_NAME`;
- `CORS_ORIGINS`;
- `DEFAULT_TIMEZONE`;

## Backups

Минимальный backup v1:

- ежедневный `pg_dump`;
- копирование uploads;
- retention 14 дней;
- инструкция восстановления в `docs/runbooks/restore.md`.

## Testing strategy

### Backend unit tests

Проверять:

- Excel normalization;
- import validation;
- route validation;
- plan generation;
- movement quantity invariants;
- transfer acceptance mismatch;
- defect creation.

### Backend integration tests

Проверять полный поток:

1. создать изделие;
2. создать BOM;
3. создать маршрут;
4. импортировать Excel;
5. утвердить план;
6. создать release batch;
7. сгенерировать задачи;
8. выдать в работу;
9. выполнить;
10. передать;
11. принять с расхождением;
12. выпустить финальную продукцию.

### Frontend tests

Минимально:

- smoke test приложения;
- импортный flow;
- section task flow;
- transfer receive flow.

### E2E tests

Использовать Playwright для сценария:

`login -> create production plan -> upload Excel -> preview diff -> apply change set -> approve positions -> create release batch -> release -> section task -> transfer -> receive -> dashboard`

## Observability v1

Локальная система не требует сложного мониторинга, но backend должен писать структурированные логи:

- upload/import errors;
- validation errors;
- plan generation start/end/failure;
- movement creation;
- transfer acceptance;
- auth failures.

## Security v1

- password hashing через `bcrypt` или `argon2`;
- httpOnly cookie или Bearer JWT;
- CSRF защита, если используется cookie auth;
- role checks на backend, не только в frontend;
- uploaded files не отдавать напрямую без auth;
- ограничить размер Excel-файла;
- запретить upload не `.xlsx`.

## Migration policy

- каждая схема БД идет через Alembic migration;
- seed data отдельной командой;
- миграции должны быть обратимыми там, где это разумно;
- данные production-like не пересоздавать через drop/create.
