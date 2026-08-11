# AGENTS.md — KTM-2000

## Workspace harness

Этот репозиторий — часть multi-project workspace **VibeCoding**.
Общая карта, порты и cross-project правила: [`../_harness/AGENTS.md`](../_harness/AGENTS.md)
и [`../_harness/memory/structure.md`](../_harness/memory/structure.md).
Локальные правила **этого** файла главнее harness при конфликте.

---

Bootstrap-инструкции для AI-агентов. Детали — в `docs/` и вложенных `AGENTS.md`.

## Проект

Локальная MES-система: планирование, shopfloor, stock ledger, импорт Excel.
Стек: Python 3.12 / FastAPI / SQLAlchemy async / React 19 / PostgreSQL 15 (Docker).

## Команды (из корня)

```bash
npm run dev                    # Postgres + migrate + backend :8010 + frontend :5172
npm run db:makemigrate -- "…"  # Новая миграция Alembic
npm run db:migrate             # Применить миграции
npm run db:seed                # Демо-данные
npm run test:pytest:fast       # Тесты backend (параллельно, рекомендуется)
npm run test:pytest:mon        # Только изменённые тесты
npm run test:pytest:lf         # Только упавшие тесты
npm run test:db:cleanup        # Уборка осиротевших тестовых БД (TTL 24h)
```

## Tests

`npm run test:pytest` is the default parallel test command.

It runs pytest with xdist (`-n auto`) against an isolated per-run
PostgreSQL database.

Every invocation creates its own test database. Multiple test runs may
execute concurrently without sharing or dropping each other's databases.

При нескольких параллельных агентах задавайте `PYTEST_NUM_WORKERS` (например `4`):
иначе каждый `-n auto` захватит все ядра и машина перестанет отвечать.

`npm run test:pytest:full` runs the same suite serially.

Do not use `test:db:down` from test launchers.

Отдельный тест — через launcher (изолированная БД):
`npm run test:pytest -- -k shopflow`
Отдельный тест без изоляции (serial, общая статичная БД, только отладка):
`cd backend && python -m pytest tests/test_shopfloor_api.py::test_name -v`

## Разведка

| Тип | Инструмент | Когда |
|-----|------------|-------|
| Код, символы, flow | **CodeGraph MCP** (`codegraph_explore`) | Всегда для codebase |
| Внешние best practices | **Exa MCP** (`web_search_exa`) | Внешняя разведка скаутов |
| Доки фреймворков | **Context7 MCP** | API reference библиотек |
| Open source паттерны | **gh_grep MCP** | Поиск по GitHub |

> Не используйте `list_dir` / `grep` для поиска символов — только CodeGraph.
> После значимых правок кода: `npx @colbymchenry/codegraph sync`

## MCP-инструменты и плагин lazy-load

В этом окружении включён плагин **lazy-load** (`~/.opencode/plugins/lazy-load.ts`,
подключается через `~/.opencode/opencode.jsonc`). Он убирает из LLM-запросов все
инструменты, кроме шлюза `load_tool`. Любой инструмент (встроенный или MCP) вызывается так:

1. `load_tool({ name: "<tool>" })` — получить инструкции и JSON-схему параметров;
2. на следующем ходу вызвать реальный инструмент напрямую.

MCP-серверы настроены в `~/.config/opencode/opencode.json` (секция `mcp`). Проверить
статус подключения: `opencode mcp list`. MCP-тулзы НЕ попадают в pointer list
`load_tool`, но зарегистрированы и вызываются напрямую.

Chrome DevTools (браузерная автоматизация) — префикс `chrome-devtools_*`
(например `chrome-devtools_navigate_page`, `chrome-devtools_take_snapshot`,
`chrome-devtools_click`). Порядок: сначала `load_tool({ name: "chrome-devtools_<tool>" })`,
затем прямой вызов.

## Документация (указатели)

| Файл | Содержание |
|------|------------|
| [`docs/context-index.md`](docs/context-index.md) | Карта всей документации |
| [`docs/project-overview.md`](docs/project-overview.md) | Архитектура, домен, UI-модули |
| [`docs/GETTING_STARTED.md`](docs/GETTING_STARTED.md) | Установка с нуля |
| [`docs/testing-guide.md`](docs/testing-guide.md) | Маршрутизатор тестирования |
| [`backend/tests/AGENTS.md`](backend/tests/AGENTS.md) | **Канон pytest** |
| [`backend/AGENTS.md`](backend/AGENTS.md) | Backend-конвенции |
| [`frontend/AGENTS.md`](frontend/AGENTS.md) | FSD, Vitest |
| [`frontend/e2e/AGENTS.md`](frontend/e2e/AGENTS.md) | **Канон E2E** (Playwright) |
| [`docs/agent-registry.md`](docs/agent-registry.md) | Субагенты, порты, MCP-матрица |

## Оркестрация

Режим `/orchestrator-hands` → [`.agents/skills/orchestrator-hands/SKILL.md`](.agents/skills/orchestrator-hands/SKILL.md)

Оркестратор пишет спеки, исполнители работают по ним. Скаут (код) → CodeGraph. Скаут (внешний) → Exa.

## Стандарты кода

1. Edge cases — валидация, ошибки, крайние случаи; без placeholders.
2. Backend — только `AsyncSession`.
3. Frontend — FSD, без cross-imports между features.
4. Коммиты — conventional commits на русском (`feat: …`, `fix: …`).
5. Stock ledger — `StockTransaction` единый источник правды; детали → `docs/project-overview.md`.
6. Transfer ↔ StockTransaction integrity — `assert_no_invariants_violations` в тестах.

## CodeGraph CLI

```bash
npx @colbymchenry/codegraph status
npx @colbymchenry/codegraph query <symbol>
npx @colbymchenry/codegraph callers <method>
npx @colbymchenry/codegraph impact <symbol>
npx @colbymchenry/codegraph sync
```

## Agent skills

### Issue tracker

Issues are tracked in GitHub Issues for `mavkasgit/ktm2000` via the `gh` CLI. See `docs/agents/issue-tracker.md`.

### Triage labels

Default five-role vocabulary (needs-triage, needs-info, ready-for-agent, ready-for-human, wontfix). See `docs/agents/triage-labels.md`.

### Domain docs

Single-context layout — one `CONTEXT.md` + `docs/adr/` at root. See `docs/agents/domain.md`.