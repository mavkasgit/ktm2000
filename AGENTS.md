# AGENTS.md — KTM-2000

Bootstrap-инструкции для AI-агентов. Детали — в `docs/` и вложенных `AGENTS.md`.

## Проект

Локальная MES-система: планирование, shopfloor, stock ledger, импорт Excel.
Стек: Python 3.12 / FastAPI / SQLAlchemy async / React 18.3 / PostgreSQL 15 (Docker).

## Команды (из корня)

```bash
npm run dev                    # Postgres + migrate + backend :8012 + frontend :5172
npm run db:makemigrate -- "…"  # Новая миграция Alembic
npm run db:migrate             # Применить миграции
npm run db:seed                # Демо-данные
npm run test:pytest            # Тесты backend (параллельно, дефолт)
npm run test:pytest:full       # Полный прогон в один поток
npm run test:pytest:mon        # Только изменённые тесты
npm run test:pytest:lf         # Только упавшие тесты
npm run test:db:cleanup        # Уборка осиротевших тестовых БД (TTL 24h)
```

Порты dev: Postgres `5440`, backend `8012`, frontend `5172`.

## Тесты

Канон pytest → [`backend/tests/AGENTS.md`](backend/tests/AGENTS.md).

- Каждый прогон идёт через launcher `scripts/test-run.ps1`: он создаёт свою БД `ktm2000_test_<runid>` и в `finally` дропает только её. Параллельные прогоны не видят и не удаляют чужие БД.
- При нескольких параллельных агентах задавайте `PYTEST_NUM_WORKERS` (например `4`): иначе каждый `-n auto` захватит все ядра и машина перестанет отвечать.
- Отдельный тест — через launcher (изолированная БД): `npm run test:pytest -- -k shopflow`.
- Отладка без изоляции (serial, общая статичная БД, только отладка): `cd backend && python -m pytest tests/test_shopfloor_api.py::test_name -v`.
- `test:db:down` из тестовых launcher'ов не использовать.

## Разведка

- Код, символы, flow — **CodeGraph MCP** (`codegraph_explore`). Не использовать `list_dir` / `grep` для поиска символов.
- Внешние best practices — **Exa MCP** (`web_search_exa` / `web_search`).
- Полная матрица MCP → [`docs/agent-registry.md`](docs/agent-registry.md).
- После значимых правок кода: `npx @colbymchenry/codegraph sync`.

## Чужие правки в рабочем дереве

Перед любым изменением файлов — `git status`. Правило обязательно для всех
агентов репо:

1. **Свои** правки — только файлы из спеки/тикета своей задачи, которые
   изменились после первого действия агента и объяснимы из истории его
   сессии. На старте работы агент фиксирует список файлов задачи и
   baseline `git status`.
2. **Чужие** правки (любое незакоммиченное вне этого списка) — никогда
   не ревертировать, не перезаписывать, не «чинить», не прятать в stash
   и не включать в свои коммиты.
3. Пересечение с чужой зоной обнаружено **до** правки → работу не начинать,
   вопрос пользователю и ожидание решения. Обнаружено **в процессе**
   (чужой агент изменил нужный файл) → замереть: не сохранять поверх,
   доложить и ждать. Молча «обходить» конфликт другой реализацией —
   запрещено.
4. Коммиты при живом WIP — только точечный `git add <свои файлы>`;
   `git add .` / `git add -A` запрещён, пока в дереве есть чужие изменения.
5. Исключение — прямая команда пользователя («убери в stash»,
   «закоммить всё»): она главнее настоящего правила.

## Стандарты кода

1. Edge cases — валидация, ошибки, крайние случаи; без placeholders.
2. Backend — только `AsyncSession`.
3. Frontend — FSD, без cross-imports между features.
4. Коммиты — conventional commits на русском (`feat: …`, `fix: …`).
5. Stock ledger — `StockTransaction` единый источник правды; детали → `docs/project-overview.md`.
6. Transfer ↔ StockTransaction integrity — `assert_no_invariants_violations` в тестах.

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
| [`docs/agent-registry.md`](docs/agent-registry.md) | Порты, MCP-матрица |

## Agent skills

### Issue tracker

Issues are tracked in GitHub Issues for `mavkasgit/ktm2000` via the `gh` CLI. See `docs/agents/issue-tracker.md`.

### Triage labels

Default five-role vocabulary (needs-triage, needs-info, ready-for-agent, ready-for-human, wontfix). See `docs/agents/triage-labels.md`.

### Domain docs

Single-context layout — one `CONTEXT.md` + `docs/adr/` at root. See `docs/agents/domain.md`.
