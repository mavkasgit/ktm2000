# Testing Guide — KTM-2000

Маршрутизатор по тестированию. Детали — в AGENTS.md рядом с кодом.

## Уровни тестирования

| Уровень | Инструмент | Канон / команды |
|---------|------------|-------|
| Backend | pytest | [`backend/tests/AGENTS.md`](../backend/tests/AGENTS.md) |
| Frontend unit | Vitest | [`frontend/AGENTS.md`](../frontend/AGENTS.md) — команды |
| E2E | Playwright | [`frontend/e2e/AGENTS.md`](../frontend/e2e/AGENTS.md) |

## Быстрый старт

```bash
npm run test:pytest            # backend, параллельно, изолированная per-run БД, без slow
npm run test:pytest:full       # backend, серийно, весь набор включая slow
npm --prefix frontend run test    # Vitest
npm run test:e2e             # Playwright, отдельный стенд (своя БД и порты)
```

## CI (фон)

Источник правды — локальный гейт ([`docs/quality/gates.md`](quality/gates.md)):
`pre-commit` по staged-файлам и умный `pre-push` по `git diff origin/main...HEAD`.
GitHub Actions остаётся вторым взглядом на push/PR; branch protection больше не
требует PR и required checks — только запрет force-push и удаления `main`.
Отключение Actions не отключает гейт.

Команды шагов в workflow не дублируются: CI зовёт `npm run gate -- --only=<шаг>`
(#364), то есть ту же команду, что и локально. Имя чека — `name:` джоба, а не
`name:` workflow.

| Workflow | Джоб | Что делает | Где блокирует локально |
|----------|------|------------|------------------------|
| `migrations.yml` | `migrations` | alembic + миграционные тесты + `labels-check`, `seeds-validate`, `profile-settings-manifest` | backend scope (кроме `alembic-drift` — он CI-only) |
| `backend-tests.yml` | `backend tests` | `backend-test-count` + pytest под `coverage` (`--fail-under=73`) | backend scope |
| `frontend-tests.yml` | `frontend tests` | `frontend-types`, `frontend-lint`, `frontend-unit`, `frontend-test-count`, `dev-deps` | frontend scope |
| `frontend-tests.yml` | `frontend build` | `frontend-build`: `vite build` + порог пакета | frontend scope |
| `ruff.yml` | `ruff` | `ruff` — 0 находок | backend scope |
| `ci-lint.yml` | `ci-lint` | jactionlint + `registry` по SHA | docs/full scope |
| `deps-audit.yml` | `deps audit` | osv-scanner, расписание | не входит |
| `docs.yml` | `docs` | `docs-links`, `adr-index`, `scripts-tests` | docs/full scope |
| `sync.yml` | `sync` | `verify-sync` с `mavkasgit/hrms` | pre-push `verify-sync` |
| `e2e-smoke.yml` | `e2e smoke` | `@smoke` на своей БД | отдельно `npm run gate:e2e` |

`paths`-фильтры уровня workflow остаются у `docs.yml` и `e2e-smoke.yml`: в фоне
они безопасны, потому что GitHub больше ничего не блокирует. Локальный гейт
скоуп считает сам ([`scripts/ci/changed-scopes.mjs`](../scripts/ci/changed-scopes.mjs)),
а не через `paths`.

`e2e` не входит в pre-push: у него свой стенд и слот семафора. Перед релизом —
`npm run gate:e2e`; серия «10 зелёных на main» остаётся метрикой стабильности,
но не условием merge.

Гейт покрытия: `coverage` (пин под бейзлайн из `docs/night/BASELINE.md`), версия —
из `backend/requirements-dev.txt` (#377), литерала в workflow нет; актуальное
значение — колонка `coverage` в [`docs/toolchain.md`](toolchain.md).
Расхождение CI ↔ локального замера — сначала разбирать, порог не подгонять.
Прогон параллельный (`-n 4 --dist loadfile`, #378): coverage в каждом воркере
стартует сам (`COVERAGE_PROCESS_START` + `sitecustomize.py`) и сводится
`coverage combine` до гейта, иначе под xdist мерился бы только диспетчер.
Замер на одной ревизии (0bd84c00, 2026-11-18, весь набор включая `slow`):
serial 983.9 с против 290.1 с на `-n 4 --dist loadfile` (−70.5%), в обоих
2464 passed / 2 skipped. Чередование 2+2 через `workflow_dispatch` — после
merge: dispatch берёт workflow только с default-ветки.

## Стенд E2E

`npm run test:e2e` не трогает devstack: поднимает **свою** БД `ktm2000_e2e`
на тестовом Postgres (`:5441`) и слушает **свои** порты — два свободных порта
ОС, которые [`frontend/scripts/run-e2e.mjs`](../frontend/scripts/run-e2e.mjs)
выбирает на каждый прогон. Статических адресов у стенда нет, поэтому
осиротевший стек прерванного прогона следующий прогон не срывает. Источник
правды для БД и хранилища — [`.env.e2e`](../.env.e2e); порты из него
используются только когда заданы снаружи (прогон против стенка, поднятого
руками, `PW_REUSE_STACK=1`). Поэтому прогон идёт параллельно с работой в
основном дереве.

Подготовка прогона (`e2e:prep`) поднимает тестовый Postgres, создаёт БД стенда
(и отказывается, если DSN нацелен на общую dev-БД), накатывает миграции и сиды
**только** на неё. Детали и отладка — [`frontend/e2e/AGENTS.md`](../frontend/e2e/AGENTS.md).

## npm-скрипты backend

Все `test:pytest*` идут через launcher `scripts/test-run.ps1`, который создаёт
уникальную БД `ktm2000_test_<runid>` на каждый прогон, запускает pytest и
дропает только свою БД. Несколько запусков могут идти параллельно.

| Команда | Назначение |
|---------|------------|
| `npm run test:pytest` | Параллельный прогон **без slow-тестов** (см. ниже) |
| `npm run test:pytest:full` | Полный прогон в один поток (slow-тесты включены) |
| `npm run test:pytest:mon` | Только изменённые (testmon; кеш — `backend/.testmondata`, в git не попадает), без slow-тестов |
| `npm run test:pytest:lf` | Только упавшие, без slow-тестов |
| `npm run test:db:cleanup` | Уборка orphan run-DB по TTL (24h) **и** старых каталогов storage тестов |
| `npm run test:hygiene` | Report-only отчёт по мёртвым импортам в тестах (stdlib) |
| `npm run test:db:up` / `test:db:wait` | Поднять тестовый Postgres (:5441) |
| `npm run test:pytest -- --keep-db` | Прогон, который **оставляет** run-DB для разбора (обычный прогон её дропает) |
| `python scripts/test-db.py drop --force <db>` | Убрать базу без owner-строки (`ktm_mig_*` от прерванного прогона миграционных тестов); отказывает при активных соединениях и на служебных именах |

### Slow-тесты

Девять интеграционных тестов демо-сидера (`test_packing_plan_demo_seeder.py`,
маркер `slow`, ~60s суммарно) в дефолтном прогоне **не выполняются** — они
гоняются в `--full`, в CI и по явному запросу:

```bash
npm run test:pytest -- -m slow            # только slow-тесты
npm run test:pytest -- -m "slow or not slow"   # всё, как в CI
```

Явный `-m` от вызывающего всегда побеждает — launcher свой фильтр в этом
случае не добавляет. CI идёт полным набором независимо от лаунчера.

Оставленную `--keep-db` БД убирают вручную — `python scripts/test-db.py drop <db>`
(имя печатается в конце прогона) или TTL-уборкой `npm run test:db:cleanup`.

Каждый прогон пишет свой лог в `logs/pytest-<runid>.log` (каталог `logs/` —
локальный, в git не попадает). Тот же текст идёт на экран **по ходу** прогона,
а не после его завершения.

## Замер SQL «до/после»

Единый рецепт замера числа SQL на реальной ручке. Правило, **что именно
измерять** (identity map, «связь не нужна»), живёт в
[`backend/AGENTS.md`](../backend/AGENTS.md#форма-запросов-identity-map-и-связь-не-нужна) —
этот раздел только про инструмент.

**Суть:** движок-слушатель считает операторы по глаголам, транзакция всегда
откатывается, счётчик сбрасывается **до** вызова ручки, а ответ сверяется
побайтово. Годится и для тестовой БД (кейс в тесте), и для БД владельца
(read-only + `rollback`).

```python
import os
from collections import Counter
from time import perf_counter

from sqlalchemy import event

os.environ["DATABASE_URL"] = "<dsn>"          # до импорта app.core.config
from app.core.database import async_session, engine   # noqa: E402


async def main() -> None:
    kinds: Counter[str] = Counter()
    stack: dict[int, float] = {}

    @event.listens_for(engine.sync_engine, "before_cursor_execute")
    def before(conn, cursor, statement, parameters, context, executemany):
        stack[id(conn)] = perf_counter()
        kinds[statement.lstrip().split(" ", 1)[0].upper()] += 1

    @event.listens_for(engine.sync_engine, "after_cursor_execute")
    def after(conn, cursor, statement, parameters, context, executemany):
        stack.pop(id(conn), None)

    from app.transfers.queries import list_ready_to_transfer

    async with async_session() as session:
        try:
            counter_reset = sum(kinds.values())   # сброс ДО вызова ручки
            t0 = perf_counter()
            result = await list_ready_to_transfer(session, limit=50, offset=0)
            wall_ms = (perf_counter() - t0) * 1000
            print(dict(kinds), sum(kinds.values()) - counter_reset, wall_ms)
            print(result["items"][0])             # сверка ответа
        finally:
            await session.rollback()              # транзакция всегда откатывается
    await engine.dispose()
```

Чек-лист, без которого замер бесполезен:

1. **Счётчик сбрасывается перед вызовом ручки**, иначе в сумму попадает
   подготовка (сбор фикстуры, выпуск плана, выпуск материала).
2. **`rollback` в `finally`**, иначе замер на чужой БД оставляет данные. На БД
   владельца — только `SELECT`; запись проверяется на своей клон-БД.
3. **Ответ сверяется, а не только счётчик.** Один и тот же файл запускается на
   дереве «до» и «после»; `json.dumps(..., sort_keys=True, default=str)`
   обоих результатов обязан совпасть. Расхождение ответов важнее, чем
   изменение числа запросов.
4. **Бюджет времени — вторичен** (под нагрузкой он скачет), решение принимается
   по числу SQL.
5. **Проверить, что ветка вообще выполнялась.** Ноль SQL может означать «данных
   нет», а не «оптимизация сработала» — см. правило про identity map.

Тестовая БД: `infra/compose/docker-compose.test.yml` (контейнер общий, run-DB
эфемерные). Подробности изоляции, правила написания тестов, Windows warning →
[`backend/tests/AGENTS.md`](../backend/tests/AGENTS.md).
