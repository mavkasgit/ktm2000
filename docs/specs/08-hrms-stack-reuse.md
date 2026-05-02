# 08. HRMS Stack Reuse Review

## Цель

Разобрать проект `C:\Users\user\VibeCoding\hrms` как успешный внутренний референс и решить, что стоит перенести в FactoryPlan для единообразия систем и уменьшения лишней работы.

## Краткий вывод

`hrms` уже близок к стеку, который мы планировали для FactoryPlan:

- FastAPI backend;
- async SQLAlchemy;
- Alembic;
- PostgreSQL;
- Pydantic v2;
- python-calamine для чтения Excel;
- React + Vite + TypeScript;
- React Router;
- TanStack Query;
- axios API client;
- Tailwind + Radix/shadcn-style UI;
- Playwright e2e;
- dev/test/prod Docker Compose окружения;
- backup/restore через backend UI.

Рекомендация: FactoryPlan лучше строить как технологически родственную систему, но с более строгой доменной архитектурой для производственного учета: ledger movements, release batches, immutable released positions и корректировки.

## Что стоит переиспользовать почти напрямую

### 1. Общая структура репозитория

HRMS:

```text
backend/
frontend/
infra/
e2e/
docs/
scripts/
data/
logs/
package.json
Makefile
playwright.config.ts
```

Для FactoryPlan стоит принять такую же структуру.

Плюсы:

- одинаковые команды запуска;
- одинаковое расположение backend/frontend/infra;
- проще сопровождать две локальные системы;
- можно переносить e2e helpers и UI-компоненты.

Решение для FactoryPlan:

```text
backend/
frontend/
infra/
e2e/
docs/
scripts/
data/
logs/
```

### 2. Dev/test/prod окружения

HRMS использует:

- `.env.dev`;
- `.env.test`;
- `.env.prod`;
- `infra/docker-compose.dev.yml`;
- `infra/docker-compose.test.yml`;
- `infra/docker-compose.prod.yml`;
- root `package.json` scripts для запуска.

Для FactoryPlan стоит повторить этот подход.

Нужно изменить только имена:

- `hrms-postgres` -> `factoryplan-postgres`;
- `hrms_dev` -> `factoryplan_dev`;
- `hrms_test` -> `factoryplan_test`;
- `hrms_prod` -> `factoryplan_prod`;
- порты подобрать так, чтобы системы могли работать рядом.

### 3. Backend foundation

HRMS backend:

- `FastAPI`;
- `sqlalchemy[asyncio]`;
- `asyncpg`;
- `alembic`;
- `pydantic`;
- `pydantic-settings`;
- `structlog`;
- `python-jose`;
- `passlib[bcrypt]`;
- `python-multipart`;
- `httpx`;
- `python-dateutil`;
- `python-calamine`;
- `pytest`;
- `pytest-asyncio`.

Для FactoryPlan стоит взять это как базу.

Изменения:

- добавить `decimal`-ориентированные доменные валидаторы количества;
- добавить строгие сервисы транзакций для `Movement`;
- добавить background worker только когда импорт/отчеты реально станут тяжелыми;
- не тащить `python-docx`, `mammoth`, OnlyOffice и fonts, если не нужны производственные документы.

### 4. Async SQLAlchemy pattern

HRMS использует:

- `create_async_engine`;
- `async_sessionmaker`;
- `AsyncSession`;
- dependency `get_db()`;
- commit/rollback внутри dependency.

Это можно взять.

Для FactoryPlan нужно усилить:

- для операций движения количества явно использовать service-level transaction;
- не делать несколько независимых commits внутри одного бизнес-действия;
- для ledger/cache обновлений держать `Movement` и cache totals в одной транзакции.

### 5. Config через pydantic-settings

HRMS `Settings` хорошо подходит как шаблон.

Для FactoryPlan нужны аналогичные настройки:

- `DATABASE_URL`;
- `ENV`;
- `SECRET_KEY`;
- `ACCESS_TOKEN_EXPIRE_MINUTES`;
- `UPLOADS_PATH`;
- `BACKUPS_PATH`;
- `POSTGRES_CONTAINER_NAME`;
- `LOG_LEVEL`;
- `LOG_FILE`;
- `DB_POOL_SIZE`;
- `DB_MAX_OVERFLOW`;
- `SQL_ECHO`.

Дополнительно для FactoryPlan:

- `MAX_EXCEL_SIZE`;
- `IMPORT_PREVIEW_ROWS`;
- `DEFAULT_TIMEZONE`;
- `CACHE_REBUILD_BATCH_SIZE`.

### 6. Excel parsing через python-calamine

HRMS уже использует:

```python
from python_calamine import CalamineWorkbook
```

Идеи, которые стоит перенести:

- чтение из `BytesIO`;
- список листов;
- выбор листа по индексу;
- preview заголовков и строк;
- column mapping до подтверждения импорта.

Что нужно сделать строже в FactoryPlan:

- импорт не должен сразу менять production plan;
- сначала создается `ImportBatch`;
- затем `PlanChangeSet`;
- затем пользователь применяет diff;
- обязательна возможность rollback до запуска позиций.

`openpyxl` можно оставить только в dev/test dependencies для генерации тестовых `.xlsx` файлов или Excel-экспортов.

### 7. Frontend stack

HRMS frontend:

- React 18;
- Vite 6;
- TypeScript;
- React Router;
- TanStack Query;
- axios;
- Tailwind;
- Radix primitives;
- lucide-react;
- date-fns;
- Recharts;
- Vitest.

Для FactoryPlan стоит использовать тот же набор.

Решение:

- использовать `axios client`, чтобы системы были единообразны;
- Zustand пока не добавлять, если хватает URL params + TanStack Query + локального state;
- shadcn-style components перенести как стартовый UI kit.

### 8. Shared UI components

В HRMS уже есть:

- `button`;
- `table`;
- `dialog`;
- `alert-dialog`;
- `input`;
- `select`;
- `checkbox`;
- `popover`;
- `date-picker`;
- `tabs`;
- `badge`;
- `skeleton`;
- `tooltip`;
- `sidebar`;
- `empty-state`;
- `combobox-create`;
- `tag-picker`.

Для FactoryPlan стоит взять:

- `button`;
- `table`;
- `dialog`;
- `alert-dialog`;
- `input`;
- `select`;
- `date-picker`;
- `badge`;
- `sidebar`;
- `empty-state`;
- `skeleton`;
- `tooltip`.

Не брать на старте:

- `tag-picker`, если теги не нужны в производственной модели;
- HR-specific forms/pages.

### 9. Frontend architecture

HRMS использует понятное разделение:

```text
src/app/
src/pages/
src/entities/<domain>/
src/features/<feature>/
src/shared/
```

Это стоит повторить.

Для FactoryPlan:

```text
src/entities/product/
src/entities/section/
src/entities/production-plan/
src/entities/release-batch/
src/entities/work-task/
src/entities/transfer/
src/entities/defect/
src/features/import-plan/
src/features/release-planning/
src/features/shopfloor-task-actions/
src/features/defect-resolution/
src/pages/ProductionPlansPage.tsx
src/pages/SectionPlanPage.tsx
src/pages/TransfersPage.tsx
src/pages/DashboardPage.tsx
```

### 10. TanStack Query hooks

HRMS pattern:

- `entities/<entity>/api.ts`;
- `entities/<entity>/types.ts`;
- `entities/<entity>/use<Entity>.ts`;
- mutations invalidate related query keys.

Это стоит перенести.

Для FactoryPlan важно заранее стандартизировать query keys:

```ts
["production-plans"]
["production-plan", planId]
["plan-positions", planId]
["release-batches", planId]
["release-batch", batchId]
["section-tasks", sectionId, filters]
["task", taskId]
["task-movements", taskId]
["transfers", filters]
["defects", filters]
["dashboard", planId]
```

### 11. Playwright e2e

HRMS уже имеет:

- `e2e/ui`;
- `e2e/api`;
- `e2e/domain`;
- page objects в `e2e/pages`;
- fixtures/helpers.

Для FactoryPlan стоит повторить это с первого milestone.

Минимальные e2e:

- `master-data-lifecycle.spec.ts`;
- `excel-import-diff.spec.ts`;
- `release-batch-generation.spec.ts`;
- `section-task-flow.spec.ts`;
- `transfer-acceptance.spec.ts`;
- `defect-rework.spec.ts`.

### 12. Backup/restore

HRMS имеет сильный модуль backup:

- list backups;
- create backup;
- download;
- preview;
- restore;
- upload restore;
- storage summary;
- fallback через Docker container.

Для FactoryPlan это особенно полезно из-за требования локальной системы.

Что перенести:

- `BACKUPS_PATH`;
- `POSTGRES_CONTAINER_NAME`;
- backup archive with manifest;
- preview before restore;
- confirmation by database name;
- running `alembic upgrade head` after restore.

Что изменить:

- добавить backup uploads: Excel-файлы, импортные оригиналы, производственные вложения;
- добавить `movement/cache consistency check` после restore;
- не делать destructive restore без отдельного admin permission.

## Что переносить осторожно

### 1. Auth

В HRMS auth частично stub-like: местами используется `_get_current_user_stub`.

FactoryPlan сразу нуждается в ролях:

- `admin`;
- `planner`;
- `section_manager`;
- `operator`;
- `viewer`.

Можно переиспользовать:

- JWT;
- bcrypt/passlib;
- axios Authorization interceptor.

Нельзя переносить:

- stub текущего пользователя;
- проверки прав только на frontend.

### 2. Integer IDs

HRMS модели в основном используют integer ids.

Решение для FactoryPlan MVP: использовать `bigint generated always as identity primary key`.

Причины:

- FactoryPlan локальный;
- один сервер;
- синхронизации между независимыми нодами нет;
- HRMS уже использует числовые id;
- важны простые логи, отладка, тесты и читаемость;
- бизнес-сущности все равно требуют отдельные `plan_no`, `batch_no`, `transfer_no`;
- импорт дедуплицируется через `source_*` ключи, а не через PK.

Формат:

```sql
id bigint generated always as identity primary key
plan_no text not null unique
source_system text null
source_ref text null
source_fingerprint text null
file_sha256 text null
source_row_hash text null
external_plan_id text null
```

UUID не используется как PK в MVP. Если позже появится внешний API, можно добавить `public_id uuid unique` как отдельное поле без замены внутренних связей.

### 3. Audit logs

HRMS пишет аудит в файл и потом парсит строки.

Для FactoryPlan этого недостаточно: производственный учет требует структурированный аудит в БД.

Рекомендация:

- оставить structlog + rotating file logs для технических логов;
- бизнес-аудит хранить в таблицах: `movements`, `plan_adjustments`, `plan_change_sets`, `defects`, `transfers`;
- отдельный file audit parser не переносить как основной механизм.

### 4. Global exception handler

HRMS возвращает `{"detail": str(exc)}` для необработанных ошибок.

Для dev это удобно, для production не стоит.

Рекомендация:

- оставить structured error model;
- в prod не возвращать stack/internal details;
- в dev показывать подробности.

### 5. Repository layer

HRMS использует repositories для части сущностей, но не везде строго.

Для FactoryPlan доменная логика сложнее, поэтому лучше:

- repositories только для DB access;
- services для бизнес-операций;
- все производственные инварианты держать в services;
- API routers не должны напрямую собирать сложные транзакции.

## Что не переносить

- OnlyOffice integration;
- document generation stack;
- HR-specific order/template logic;
- employee/vacation domain patterns;
- file-based business audit as source of truth;
- direct confirm-import flow, который сразу пишет данные без `PlanChangeSet`.

## Что зафиксировано в FactoryPlan спеках

### 1. Frontend API client

В [06-api-frontend.md](06-api-frontend.md) зафиксирован `axios client`, чтобы совпадать с HRMS.

Решение: axios как в HRMS.

### 2. Zustand

Zustand не входит в обязательный стек MVP.

HRMS обходится без Zustand, используя TanStack Query и локальный state.

Решение: не добавлять Zustand в MVP. Использовать TanStack Query, URL params и локальный state, как в HRMS. Zustand можно добавить позже, если появится реальная сложность глобального UI-состояния.

### 3. UI kit

Вместо абстрактного `shadcn/ui или MUI` зафиксирован HRMS-подход:

- Tailwind;
- Radix primitives;
- class-variance-authority;
- shared UI components;
- lucide-react.

Решение: не брать MUI. Использовать Tailwind/Radix/shadcn-style shared components как в HRMS.

### 4. Docker layout

Вместо одного `docker-compose.yml` лучше сделать как HRMS:

- `infra/docker-compose.dev.yml`;
- `infra/docker-compose.test.yml`;
- `infra/docker-compose.prod.yml`;
- root scripts в `package.json`.

### 5. Testing layout

Повторить HRMS:

- backend `pytest`;
- frontend `vitest`;
- e2e `playwright`;
- отдельные e2e папки `ui`, `api`, `domain`.

## Зафиксированные решения

1. FactoryPlan использует `bigint identity` PK, а не UUID.
2. API client: axios как в HRMS.
3. Zustand не входит в MVP.
4. UI stack: Tailwind + Radix + shared UI components, без MUI.
5. Infra layout повторяет HRMS: `infra/docker-compose.dev.yml`, `test`, `prod`.
6. Excel reader: `python-calamine`.
7. Бизнес-аудит идет через доменные таблицы FactoryPlan; file-based audit HRMS не переносится как источник истины.

## Открытые решения

1. Переносим backup/restore module в Milestone 1 или выносим в Milestone 2?
2. Нужен ли Redis/worker в MVP, если HRMS обходится без него для большей части задач?
3. Добавлять ли отдельную `audit_events` таблицу поверх доменных таблиц или пока достаточно `movements`, `transfers`, `defects`, `plan_adjustments`, `plan_change_sets`?

## Предлагаемая корректировка FactoryPlan стека

Backend:

- Python 3.12;
- FastAPI;
- Pydantic v2;
- pydantic-settings;
- SQLAlchemy asyncio;
- asyncpg;
- Alembic;
- PostgreSQL;
- structlog;
- python-jose;
- passlib/bcrypt;
- python-multipart;
- python-calamine;
- pytest;
- pytest-asyncio.

Frontend:

- React 18;
- Vite;
- TypeScript;
- React Router;
- TanStack Query;
- axios;
- Tailwind CSS;
- Radix UI primitives;
- class-variance-authority;
- lucide-react;
- date-fns;
- Recharts;
- Vitest.

Infrastructure:

- `infra/docker-compose.dev.yml`;
- `infra/docker-compose.test.yml`;
- `infra/docker-compose.prod.yml`;
- PostgreSQL 15 alpine;
- local data/logs/uploads/backups directories;
- root `package.json` orchestration scripts;
- Playwright e2e.
