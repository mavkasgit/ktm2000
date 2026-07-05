<div align="center">

<img src="./frontend/public/favicon.svg" alt="KTM-2000 Logo" align="center" height="64" />

# KTM-2000

Локальная система производственного планирования и контроля для цехового производства.

[![TypeScript](https://img.shields.io/badge/TypeScript-blue?style=flat-square&logo=typescript&logoColor=white)](https://www.typescriptlang.org)
[![Python](https://img.shields.io/badge/Python-3.12+-blue?style=flat-square&logo=python&logoColor=white)](https://www.python.org)
[![FastAPI](https://img.shields.io/badge/FastAPI-v0.100+-green?style=flat-square&logo=fastapi&logoColor=white)](https://fastapi.tiangolo.com)
[![React](https://img.shields.io/badge/React-19-blue?style=flat-square&logo=react&logoColor=white)](https://react.dev)

[Обзор](#обзор) • [Возможности](#возможности) • [Быстрый старт](#быстрый-старт) • [Команды](#команды-разработки) • [Документация](#документация)

</div>

---

## Обзор

KTM-2000 — локальная MES-система для цехового производства: планирование, учёт выполнения на участках, складской ledger и импорт данных из Excel. В dev-режиме PostgreSQL работает в Docker, а backend и frontend — на хосте с hot reload.

## Возможности

- **Справочники** — номенклатура, участки/ГХП, техкарты, маршруты
- **Планирование** — формирование планов, импорт из Excel
- **Контроль выполнения** — мониторинг статусов планов и задач
- **Участки (shopfloor)** — выдача в работу, брак, переделка
- **Складской учёт** — остатки, транзакции (`StockTransaction`), передачи между участками
- **Журнал действий** — аудит операций
- **Настройки** — бэкапы БД, пользователи и роли

## Быстрый старт

```bash
npm run setup

cd backend && python -m venv .venv
.venv\Scripts\Activate.ps1          # Windows PowerShell
pip install -r requirements.txt

cp .env.example .env.dev
npm run dev
```

- Frontend: [http://localhost:5180](http://localhost:5180)
- API (Swagger): [http://localhost:8010/docs](http://localhost:8010/docs)

> [!NOTE]
> Пошаговая установка, seed и troubleshooting — [docs/GETTING_STARTED.md](docs/GETTING_STARTED.md).

## Команды разработки

| Команда | Назначение |
|---------|------------|
| `npm run dev` | Postgres + миграции + backend + frontend |
| `npm run devkill` | Остановить dev-серверы (8010, 5180) |
| `npm run devrestart` | Перезапустить dev-окружение |
| `npm run db:makemigrate -- "описание"` | Создать миграцию |
| `npm run db:migrate` | Применить миграции |
| `npm run db:seed` | Демо-данные |
| `npm run test:pytest:fast` | Тесты backend (рекомендуется) |
| `npm run prod:up` | Production в Docker |

Тестирование → [docs/testing-guide.md](docs/testing-guide.md). Production → [docs/deployment.md](docs/deployment.md).

## Документация

| Документ | Содержание |
|----------|------------|
| [docs/context-index.md](docs/context-index.md) | Индекс документации |
| [AGENTS.md](AGENTS.md) | Инструкции для AI-агентов |
| [docs/project-overview.md](docs/project-overview.md) | Архитектура и домен |
| [docs/GETTING_STARTED.md](docs/GETTING_STARTED.md) | Установка с нуля |
| [docs/testing-guide.md](docs/testing-guide.md) | Тестирование |
| [docs/deployment.md](docs/deployment.md) | Production |