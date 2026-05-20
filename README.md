# KTM-2000

Локальная система производственного планирования и контроля для цехового производства.

## Возможности

- **Участки (Shopfloor)** — управление задачами производственных участков, отображение SKU и данных плана
- **Планирование** — маршруты производства, этапы, раскрытие деталей планов
- **Секции** — гибкая настройка дат и времени планирования
- **Импорт каталогов** — загрузка номенклатуры из Excel (.xls, .xlsx) по шаблонам
- **Техкарты** — привязка технологий к продуктам
- **Производственные планы** — ручное управление этапами, финальные этапы маршрута
- **Бэкапы** — управление резервными копиями данных

## Технологический стек

| Компонент | Технология |
|---|---|
| Backend | Python 3.12+, FastAPI, SQLAlchemy (async), Alembic |
| Frontend | React 19+, Vite, shadcn/ui, TanStack Table |
| Database | PostgreSQL 15 |
| Containers | Docker Compose |

## Структура проекта

```
├── backend/            # FastAPI backend
│   └── app/
│       ├── api/        # API endpoints (auth, products, routes, shopfloor, imports...)
│       ├── core/       # конфигурация, зависимости
│       ├── models/     # SQLAlchemy модели
│       ├── schemas/    # Pydantic схемы
│       └── services/   # бизнес-логика
├── frontend/           # React frontend
│   └── src/
│       ├── app/        # корневые компоненты, роутинг
│       ├── entities/   # сущности (продукты, участки, маршруты...)
│       ├── features/   # функциональные модули (execution, planning, references, sections, settings)
│       └── shared/     # общие утилиты и компоненты
├── infra/              # Docker Compose конфигурации (dev, test, prod)
├── scripts/            # вспомогательные скрипты
├── storage/            # файловое хранилище (фото продукции, импорты)
└── data/               # данные PostgreSQL
```

## Порты

| Окружение | Frontend (external) | Postgres | Backend (internal) |
|---|---:|---:|---:|
| dev | 5180 | 5202 | 8000 |
| test | 8100 | 5212 | 8000 |
| prod | 8020 | 5432 (внутри Docker) | 8000 |

Для `dev` в Docker поднимается только PostgreSQL; backend и frontend запускаются локально.

## Быстрый старт

### 1. Установка зависимостей

```bash
npm run setup
```

Убедитесь, что установлены зависимости Python:

```bash
cd backend && pip install -r requirements.txt
```

### 2. Настройка окружения

Скопируйте `.env.example` в `.env.dev` и настройте переменные:

```bash
cp .env.example .env.dev
```

### 3. Запуск (dev)

```bash
npm run dev
```

Команда автоматически:
1. Поднимает PostgreSQL контейнер
2. Ждёт его готовности (healthcheck)
3. Применяет миграции Alembic
4. Запускает backend (`:8010`) и frontend (`:3000`)

### 4. Остановка

```bash
npm run db:down
```

## Разработка

### Миграции БД

```bash
# Создать миграцию
npm run db:makemigrate "описание изменений"

# Применить миграции
npm run db:migrate
```

### Тесты

Тесты работают против отдельной БД `ktm2000_test` на `localhost:5212`:

```bash
npm run test:pytest
```

Полный цикл тестового окружения:

```bash
npm run test:up      # поднять все сервисы
npm run test:pytest  # запустить pytest
npm run test:down    # остановить
```

## Production

### Запуск

```bash
npm run prod:up
```

Включает Cloudflare Tunnel (опционально):

```bash
npm run prod:tunnel:up
```

### Production файлы

- `.env.prod` — переменные окружения
- `infra/docker-compose.prod.yml` — конфигурация сервисов
- `infra/nginx/default.conf` — конфигурация Nginx

## NPM скрипты

| Команда | Описание |
|---|---|
| `npm run dev` | Запуск dev-окружения |
| `npm run devkill` | Остановить dev-серверы |
| `npm run devrestart` | Перезапуск dev |
| `npm run db:up/down` | PostgreSQL up/down |
| `npm run db:migrate` | Применить миграции |
| `npm run test:pytest` | Запустить тесты |
| `npm run prod:up/down` | Production up/down |
| `npm run prod:logs` | Production логи |
