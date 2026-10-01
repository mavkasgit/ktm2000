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

## CI

Автоматические workflow (решения грилла #245):

| Workflow | Триггер | Что делает |
|----------|---------|------------|
| `migrations.yml` | push, PR | alembic + миграционные тесты + проверки сидов/лейблов |
| `backend-tests.yml` | push, PR | полный pytest-набор под `coverage` (serial, `-p no:xdist -p no:testmon`) + **гейт `--fail-under=73`** |
| `frontend-tests.yml` | push, PR | `tsc -b` + vitest с покрытием и **гейтом** `statements/lines ≥ 43`, `branches ≥ 72` (решение Q5=1, замер в `BASELINE.md`) |
| `ruff.yml` | push, PR | `ruff check backend` — **блокирующая** проверка (pyflakes-ядро `F`, находок 0); стилевые и сигнальные семейства в скоуп не входят |

Гейт покрытия: `coverage==7.16.2` (пин под бейзлайн из `docs/night/BASELINE.md`);
расхождение CI ↔ локального замера — сначала разбирать, порог не подгонять.
Прогон серийный: под xdist воркеры остаются вне замера coverage.

Branch protection (required checks `migrations`, `backend tests`,
`frontend tests`, `enforce_admins: false`) включается **после** первого пуша
workflows и первого зелёного прогона — тикет #254.

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

Шесть интеграционных тестов демо-сидера (`test_packing_plan_demo_seeder.py`,
маркер `slow`, ~204s суммарно) в дефолтном прогоне **не выполняются** — они
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

`test:db:down` — только ручная остановка; тестовые прогоны его не вызывают.

Тестовая БД: `infra/compose/docker-compose.test.yml` (контейнер общий, run-DB
эфемерные). Подробности изоляции, правила написания тестов, Windows warning →
[`backend/tests/AGENTS.md`](../backend/tests/AGENTS.md).