# Context Index — KTM-2000

Карта документации проекта.

| Файл | Область | Когда использовать |
|------|---------|--------------------|
| [`README.md`](../README.md) | Точка входа (люди) | Обзор, быстрый старт, npm-команды |
| [`AGENTS.md`](../AGENTS.md) | Bootstrap (агенты) | Команды, CodeGraph, указатели |
| [`backend/AGENTS.md`](../backend/AGENTS.md) | Backend | FastAPI, stock ledger, миграции |
| [`backend/tests/AGENTS.md`](../backend/tests/AGENTS.md) | **Канон pytest** | Изоляция БД, правила, npm test-скрипты |
| [`frontend/AGENTS.md`](../frontend/AGENTS.md) | Frontend | FSD, Vitest |
| [`frontend/e2e/AGENTS.md`](../frontend/e2e/AGENTS.md) | **Канон E2E** | Playwright: env, фикстуры, спеки |
| [`project-overview.md`](project-overview.md) | Архитектура | Стек, домен, UI-модули, дерево каталогов |
| [`storage-vs-production-ui-experience.md`](storage-vs-production-ui-experience.md) | **Маршруты / UI** | «Цех / склад / транзит», `stage_kind`, контракт для фронтенда |
| [`auth-oidc.md`](auth-oidc.md) | **Auth / OIDC** | Authentik bridge, link order, dual-run, logout, env |
| [`GETTING_STARTED.md`](GETTING_STARTED.md) | Установка | Развёртывание с нуля, seed, troubleshooting |
| [`testing-guide.md`](testing-guide.md) | Тестирование | Маршрутизатор → AGENTS.md в backend/frontend |
| [`deployment.md`](deployment.md) | Деплой | Production, .env-файлы, бэкапы |
| [`agent-registry.md`](agent-registry.md) | ИИ-агенты | Порты и MCP-матрица скаутов |
| [`bulk-operations-core-v1.md`](bulk-operations-core-v1.md) | Пакетные операции | Bulk approve/delete |
| [`excel-import-10-unique-scenarios.md`](excel-import-10-unique-scenarios.md) | Импорт Excel | Сценарии и валидация |
| [`catalog-excel-format.md`](catalog-excel-format.md) | **Справочник сырья (Excel)** | Формат импорта/выгрузки, round-trip, нормы, «Фото» |
| [`excel-import-route-passport.md`](excel-import-route-passport.md) | Импорт плана | Парсинг маршрутов из Excel |
| [`plan-import-spec.md`](plan-import-spec.md) | **Импорт плана** | Спека ускорения/стабилизации импорта, коды строк, apply/rollback |
| [`adr/`](adr/) | ADR (решения) | Архитектурные решения: инварианты, откаты, миграции |
| [`research/`](research/) | Research | Исследования внешних систем (SAP, Odoo MRP/BOM) |