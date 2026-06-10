<div align="center">

<img src="./frontend/public/favicon.svg" alt="KTM-2000 Logo" align="center" height="64" />

# KTM-2000

Локальная система производственного планирования и контроля для цехового производства.

[![TypeScript](https://img.shields.io/badge/TypeScript-blue?style=flat-square&logo=typescript&logoColor=white)](https://www.typescriptlang.org)
[![Python](https://img.shields.io/badge/Python-3.12+-blue?style=flat-square&logo=python&logoColor=white)](https://www.python.org)
[![FastAPI](https://img.shields.io/badge/FastAPI-v0.100+-green?style=flat-square&logo=fastapi&logoColor=white)](https://fastapi.tiangolo.com)
[![React](https://img.shields.io/badge/React-19-blue?style=flat-square&logo=react&logoColor=white)](https://react.dev)

[Обзор](#обзор) • [Возможности](#возможности) • [Архитектура](#архитектура) • [Быстрый старт](#быстрый-старт) • [Разработка](#разработка) • [Production](#production)

</div>

---

## Обзор

KTM-2000 — это специализированное программное обеспечение для управления цеховыми процессами, отслеживания выполнения производственных планов, импорта номенклатур и ведения технологических карт. Система спроектирована для локального развертывания, обеспечивая высокую скорость работы и полную приватность данных предприятия.

> [!TIP]
> Система использует Docker-контейнеры для баз данных, а фронтенд и бэкенд в режиме разработки запускаются локально для максимального удобства отладки и горячей перезагрузки (Hot Reload).

## Возможности

- **Участки (Shopfloor):** Управление задачами производственных участков, отслеживание SKU и плановых показателей.
- **Планирование:** Визуализация маршрутов производства, этапов обработки и детализации планов.
- **Секции:** Гибкая временная настройка интервалов планирования.
- **Импорт каталогов:** Быстрый импорт номенклатуры из файлов Excel (`.xls`, `.xlsx`) по шаблонам.
- **Технологические карты:** Привязка технологических процессов и этапов к выпускаемой продукции.
- **Бэкапы:** Удобное управление резервными копиями базы данных непосредственно из интерфейса.

## Архитектура

Проект организован как монорепозиторий и разделен на три ключевые части:
1. **Frontend:** Приложение на React 19+ и TypeScript, собранное с помощью Vite. Кодовая база структурирована по методологии **Feature-Sliced Design (FSD)**.
2. **Backend:** Асинхронный API-сервис на FastAPI (Python 3.12+) с использованием SQLAlchemy и миграций Alembic.
3. **Infrastructure:** Docker Compose конфигурации для развертывания баз данных Postgres в различных окружениях (dev, test, prod).

### Структура каталогов

```
├── backend/            # Асинхронный FastAPI backend
│   └── app/
│       ├── api/        # Эндпоинты (auth, products, routes, shopfloor, imports...)
│       ├── core/       # Конфигурация, сессии БД, зависимости
│       ├── models/     # SQLAlchemy ORM модели
│       ├── schemas/    # Pydantic схемы валидации
│       └── services/   # Бизнес-логика
├── frontend/           # React frontend (Vite)
│   └── src/
│       ├── app/        # Настройки приложения, стили, роутер
│       ├── entities/   # Бизнес-сущности (продукты, участки, маршруты)
│       ├── features/   # Интерактивные фичи (execution, planning, settings...)
│       └── shared/     # UI-компоненты, API-клиенты, общие хуки
└── infra/              # Скрипты развертывания и конфигурации Docker
```

### Порты и окружение

| Окружение | Frontend (внешний) | Postgres (внешний) | Backend (внутренний) |
|---|---|---|---|
| **dev** | `5180` | `5202` | `8010` |
| **test** | `8100` | `5212` | `8010` |
| **prod** | `8020` | `5432` *(внутри Docker)* | `8010` |

---

## Быстрый старт

### 1. Установка зависимостей

Установите глобальные и фронтенд-зависимости:
```bash
npm run setup
```

Установите зависимости Python для бэкенда:
```bash
cd backend
python -m venv .venv
# Активируйте виртуальное окружение:
# Windows (PowerShell): .venv\Scripts\Activate.ps1
# Linux/macOS: source .venv/bin/activate
pip install -r requirements.txt
```

### 2. Настройка окружения

Создайте файл `.env.dev` в корневой директории на основе примера:
```bash
cp .env.example .env.dev
```

### 3. Запуск dev-окружения

```bash
npm run dev
```

> [!NOTE]
> Эта команда автоматически поднимет PostgreSQL в Docker, дождется его готовности, применит миграции Alembic и запустит локальные серверы бэкенда (`localhost:8010`) и фронтенда (`localhost:5180`).

---

## Разработка

### Миграции базы данных

При изменении ORM-моделей в `backend/app/models/` выполните:
```bash
# Генерация новой миграции
npm run db:makemigrate -- "описание изменений"

# Применение миграций
npm run db:migrate
```

### Запуск тестов

Тестирование выполняется с использованием pytest на отдельной базе данных.

> [!IMPORTANT]
> Всегда запускайте тесты из директории `backend/`, так как там находятся файлы конфигурации `pytest.ini` и `conftest.py`.

```bash
cd backend
python -m pytest tests/ -v
```

> [!TIP]
> Для ускорения прохождения всех тестов можно запускать их параллельно в 4 воркера с помощью пакета `pytest-xdist` (установите его в виртуальном окружении с помощью `pip install pytest-xdist`):
> ```bash
> python -m pytest tests/ -v -n 4
> ```

Для запуска конкретного теста:
```bash
python -m pytest tests/test_shopfloor_api.py::test_shopfloor_over_issue_rejected -v
```

> [!WARNING]
> На Windows-системах перенаправление вывода `2>&1 | head -80` ломает выполнение pytest в некоторых эмуляторах терминала (символ `2` считывается как аргумент). Запускайте тесты напрямую или используйте перенаправление в файл: `pytest tests/ -v > out.txt 2>&1` с последующим чтением файла.

---

## Production

Для запуска production-сборки в Docker контейнерах:
```bash
npm run prod:up
```

Для остановки сервисов:
```bash
npm run prod:down
```
