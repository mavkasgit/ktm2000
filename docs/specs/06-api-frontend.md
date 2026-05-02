# 06. API and Frontend

## Backend stack

- Python 3.12;
- FastAPI;
- Pydantic v2;
- SQLAlchemy 2.x;
- Alembic;
- PostgreSQL;
- Redis / RQ / Dramatiq не входят в обязательный MVP; добавить позже, если импорт или отчеты станут тяжелыми;
- python-calamine для чтения `.xlsx`.

## Frontend stack

- TypeScript;
- React;
- Vite;
- React Router;
- TanStack Query;
- axios;
- Tailwind CSS;
- Radix UI primitives;
- class-variance-authority;
- lucide-react;
- React Hook Form;
- Zod;
- TanStack Table;
- Recharts.

Frontend stack намеренно повторяет удачные общие решения HRMS. MUI и Zustand не входят в MVP.

## API modules

### Auth

- `POST /api/auth/login`
- `POST /api/auth/logout`
- `GET /api/auth/me`

### Products

- `GET /api/products`
- `POST /api/products`
- `GET /api/products/{id}`
- `PATCH /api/products/{id}`
- `GET /api/products/{id}/bom`
- `GET /api/products/{id}/route`

### Sections

- `GET /api/sections`
- `POST /api/sections`
- `PATCH /api/sections/{id}`

### BOM

- `POST /api/boms`
- `POST /api/boms/{id}/lines`
- `PATCH /api/boms/{id}`
- `DELETE /api/boms/{id}/lines/{line_id}`

### Routes

- `POST /api/routes`
- `POST /api/routes/{id}/steps`
- `PATCH /api/routes/{id}`
- `DELETE /api/routes/{id}/steps/{step_id}`

### Imports

- `POST /api/imports/production-plan/upload`
- `GET /api/imports/{id}/preview`
- `POST /api/imports/{id}/validate`
- `POST /api/imports/{id}/change-set`
- `POST /api/plan-change-sets/{id}/apply`
- `POST /api/plan-change-sets/{id}/rollback`

### Plans

- `GET /api/production-plans`
- `POST /api/production-plans`
- `GET /api/production-plans/{id}`
- `POST /api/production-plans/{id}/positions`
- `POST /api/production-plans/{id}/positions/{position_id}/approve`
- `POST /api/production-plans/{id}/adjustments`
- `GET /api/production-plans/{id}/progress`
- `GET /api/internal-plans/{id}/section-lines`

### Release Batches

- `GET /api/production-plans/{id}/release-batches`
- `POST /api/production-plans/{id}/release-batches`
- `GET /api/release-batches/{id}`
- `POST /api/release-batches/{id}/positions`
- `POST /api/release-batches/{id}/release`
- `POST /api/release-batches/{id}/cancel`

### Tasks

- `GET /api/tasks`
- `GET /api/tasks/{id}`
- `POST /api/tasks/{id}/issue`
- `POST /api/tasks/{id}/complete`
- `POST /api/tasks/{id}/final-release`
- `GET /api/tasks/{id}/movements`

### Transfers

- `GET /api/transfers`
- `POST /api/transfers`
- `POST /api/transfers/{id}/accept`
- `POST /api/transfers/{id}/cancel`

### Defects and Rework

- `GET /api/defects`
- `GET /api/defects/{id}`
- `POST /api/defects/{id}/decision`
- `GET /api/rework-tasks`
- `POST /api/rework-tasks/{id}/complete`

### Dashboard

- `GET /api/dashboard/production-plan/{id}`
- `GET /api/dashboard/sections`
- `GET /api/dashboard/bottlenecks`

## Frontend routes

- `/login`
- `/`
- `/imports`
- `/production-plans`
- `/production-plans/:id`
- `/release-batches`
- `/release-batches/:id`
- `/products`
- `/products/:id`
- `/routes/:id`
- `/sections`
- `/section-plan`
- `/tasks/:id`
- `/transfers`
- `/defects`
- `/dashboard`

## UI screens v1

### Import Excel

Состояния:

- no file;
- uploading;
- mapping columns;
- validating;
- diff preview;
- preview with errors;
- ready to apply;
- applied;
- rolled back.

### Production Plan

Показывает:

- строки плана;
- источник каждой позиции;
- статус;
- количество;
- ошибки;
- готовность к запуску;
- корректировки;
- release batches;
- кнопку создания пакета запуска после утверждения позиций.

### Release Batch

Показывает:

- тип горизонта: 2-3 дня, неделя, future preparation или ручной запуск;
- выбранные позиции;
- количество запуска по каждой позиции;
- выбранную версию маршрута;
- статус запуска;
- созданные задачи участков;
- возможность отмены, если еще нет движений.

### Product Card

Показывает:

- основные поля изделия;
- BOM;
- маршрут;
- активные планы.

### Route Editor

Показывает линейный список этапов:

- sequence;
- section;
- operation;
- norm time;
- final step.

### Section Plan

Главный экран мастера:

- задачи участка;
- доступно;
- в работе;
- выполнено;
- передано;
- брак;
- остаток;
- быстрые действия.

### Task Details

Показывает:

- карточку задачи;
- количественные итоги из кеша;
- историю движений;
- доступные действия;
- связанные передачи;
- дефекты.

Итоги в карточке задачи должны явно отличаться от истории: верхняя часть показывает быстрый кеш, ниже журнал `Movement`, из которого этот кеш восстановим.

### Transfers

Показывает:

- отправленные;
- ожидающие приемки;
- принятые;
- частично принятые;
- отклоненные.

### Defects

Показывает:

- открытые дефекты;
- причину;
- участок выявления;
- ответственный участок;
- решение;
- связанные задачи доработки;
- историю движений.

### Dashboard

Показывает:

- прогресс производственного плана;
- прогресс по изделиям;
- прогресс по участкам;
- bottlenecks;
- просроченные задачи;
- брак;
- незавершенное производство.

## Role access v1

- `admin`: все действия.
- `planner`: импорт, справочники, маршруты, генерация, dashboard.
- `section_manager`: задачи и передачи своего участка.
- `operator`: выполнение назначенных задач.
- `viewer`: только чтение.

## Frontend state rules

TanStack Query отвечает за server state.

URL params и локальный React state отвечают за UI-состояние:

- выбранный участок;
- выбранный горизонт планирования;
- открытые фильтры;
- layout preference.

Zustand не добавлять в MVP. Добавить позже только при реальной необходимости сложного глобального UI-состояния.

Формы валидировать Zod-схемами, совпадающими с Pydantic DTO по полям и ограничениям.
