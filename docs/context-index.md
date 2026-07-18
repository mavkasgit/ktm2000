# Context Index — KTM-2000

Карта документации проекта.

| Файл | Область | Когда использовать |
|------|---------|--------------------|
| [`README.md`](../README.md) | Точка входа (люди) | Обзор, быстрый старт, npm-команды |
| [`AGENTS.md`](../AGENTS.md) | Bootstrap (агенты) | Команды, CodeGraph, Exa, указатели |
| [`backend/AGENTS.md`](../backend/AGENTS.md) | Backend | FastAPI, stock ledger, миграции |
| [`backend/tests/AGENTS.md`](../backend/tests/AGENTS.md) | **Канон pytest** | Изоляция БД, правила, npm test-скрипты |
| [`frontend/AGENTS.md`](../frontend/AGENTS.md) | Frontend | FSD, Vitest |
| [`frontend/e2e/AGENTS.md`](../frontend/e2e/AGENTS.md) | **Канон E2E** | Playwright: env, фикстуры, спеки |
| `project-overview.md` | Архитектура | Стек, домен, UI-модули, дерево каталогов |
| [`auth-oidc.md`](auth-oidc.md) | **Auth / OIDC** | Authentik bridge, link order, dual-run, logout, env |
| `GETTING_STARTED.md` | Установка | Развёртывание с нуля, seed, troubleshooting |
| `testing-guide.md` | Тестирование | Маршрутизатор → AGENTS.md в backend/frontend |
| `e2e-handoff.md` | E2E handoff | Статус прогона, баги, DoD для исполнителя |
| `deployment.md` | Деплой | Production, .env-файлы, бэкапы |
| `agent-registry.md` | ИИ-агенты | Субагенты, порты, MCP-матрица скаутов |
| `bulk-operations-core-v1.md` | Пакетные операции | Bulk approve/delete |
| `excel-import-10-unique-scenarios.md` | Импорт Excel | Сценарии и валидация |
| `excel-import-route-passport.md` | Импорт техкарт | Парсинг маршрутов из Excel |