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
npm run dev                    # Postgres + migrate + backend :8010 + frontend :5180
npm run db:makemigrate -- "…"  # Новая миграция Alembic
npm run db:migrate             # Применить миграции
npm run db:seed                # Демо-данные
npm run test:pytest:fast       # Тесты backend (параллельно, рекомендуется)
npm run test:pytest:mon        # Только изменённые тесты
npm run test:pytest:lf         # Только упавшие тесты
```

Конкретный тест: `cd backend && python -m pytest tests/test_shopfloor_api.py::test_name -v`

## Разведка

| Тип | Инструмент | Когда |
|-----|------------|-------|
| Код, символы, flow | **CodeGraph MCP** (`codegraph_explore`) | Всегда для codebase |
| Внешние best practices | **Exa MCP** (`web_search_exa`) | Внешняя разведка скаутов |
| Доки фреймворков | **Context7 MCP** | API reference библиотек |
| Open source паттерны | **gh_grep MCP** | Поиск по GitHub |

> Не используйте `list_dir` / `grep` для поиска символов — только CodeGraph.
> После значимых правок кода: `npx @colbymchenry/codegraph sync`

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