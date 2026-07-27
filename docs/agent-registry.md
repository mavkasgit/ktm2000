# Agent Registry — KTM-2000

Субагенты, порты и MCP-матрица для ИИ-ассистентов. Bootstrap → [AGENTS.md](../AGENTS.md).

## Навигация по документации

| Файл | Область |
|------|---------|
| [context-index.md](context-index.md) | Карта всей документации |
| [project-overview.md](project-overview.md) | Архитектура, домен |
| [GETTING_STARTED.md](GETTING_STARTED.md) | Установка |
| [testing-guide.md](testing-guide.md) | Маршрутизатор тестов |
| [backend/tests/AGENTS.md](../backend/tests/AGENTS.md) | Канон pytest |
| [frontend/e2e/AGENTS.md](../frontend/e2e/AGENTS.md) | Канон E2E |

## MCP-матрица скаутов

| Тип разведки | MCP | Инструменты | Когда |
|--------------|-----|-------------|-------|
| Код, символы, flow | **CodeGraph** | `codegraph_explore`, `codegraph_callers`, `codegraph_impact` | Всегда для codebase |
| Внешние best practices | **Exa** | `web_search_exa`, `web_fetch_exa` | Скауты в `/orchestrator-hands`, стандарты, гайды |
| Доки фреймворков | **Context7** | `resolve-library-id`, `query-docs` | API reference библиотек |
| Open source паттерны | **gh_grep** | `searchGitHub` | Поиск по GitHub |
| Браузер / UI | **chrome-devtools** | `navigate_page`, `take_snapshot` | E2E-проверки |
| SQL-запросы | **postgres** | `query` | Отладка данных в dev-БД |

> Для внешней разведки предпочитайте **Exa**, не встроенный WebSearch.

## Порты

| Порт | Назначение |
|------|------------|
| `5180` | Frontend (dev) |
| `8010` | Backend API |
| `5440` | Postgres (dev) |
| `5441` | Postgres (test) |
| `8020` | Frontend (prod) |
| `8082` | Nginx KTM-2000 (автономный) |
| `9222` | Chrome CDP (E2E) |

## Субагенты

| Субагент | Назначение |
|----------|------------|
| `browser-checker` | Браузерные проверки |
| `docs-maintainer` | Актуализация `docs/` после задач |
| `test-runner` | Запуск pytest / Playwright |
| `test-fixer` | Починка падающих тестов |
| `server-operator` | Shell на сервере (SSH MCP) |
| `sftp-operator` | Передача файлов (SFTP MCP) |
| `server-deployer` | Координация деплоя |

## Правила

1. Код — **CodeGraph**, не grep/list_dir для символов.
2. Внешнее — **Exa MCP** для скаутов.
3. FSD на фронтенде — без cross-imports между features.
4. Edge cases — валидация, ошибки, Excel-импорт.
5. После правок кода: `npx @colbymchenry/codegraph sync`.