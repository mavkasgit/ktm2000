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
npm run test:pytest            # backend, параллельно, изолированная per-run БД (по умолчанию)
npm run test:pytest:full       # backend, серийно
npm --prefix frontend run test    # Vitest
npm run test:e2e             # Playwright, отдельный стенд (своя БД и порты)
```

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
| `npm run test:pytest` | Параллельный прогон всех тестов |
| `npm run test:pytest:fast` | Алиас `test:pytest` |
| `npm run test:pytest:full` | Полный прогон в один поток |
| `npm run test:pytest:mon` | Только изменённые (testmon) |
| `npm run test:pytest:lf` | Только упавшие |
| `npm run test:db:cleanup` | Уборка orphan run-DB по TTL (24h) |
| `npm run test:db:up` / `test:db:wait` | Поднять тестовый Postgres (:5441) |
| `npm run test:pytest -- --keep-db` | Прогон, который **оставляет** run-DB для разбора (обычный прогон её дропает) |
| `python scripts/test-db.py drop --force <db>` | Убрать базу без owner-строки (`ktm_mig_*` от прерванного прогона миграционных тестов); отказывает при активных соединениях и на служебных именах |

Оставленную `--keep-db` БД убирают вручную — `python scripts/test-db.py drop <db>`
(имя печатается в конце прогона) или TTL-уборкой `npm run test:db:cleanup`.

Каждый прогон пишет свой лог в `logs/pytest-<runid>.log` (каталог `logs/` —
локальный, в git не попадает). Тот же текст идёт на экран **по ходу** прогона,
а не после его завершения.

`test:db:down` — только ручная остановка; тестовые прогоны его не вызывают.

Тестовая БД: `infra/compose/docker-compose.test.yml` (контейнер общий, run-DB
эфемерные). Подробности изоляции, правила написания тестов, Windows warning →
[`backend/tests/AGENTS.md`](../backend/tests/AGENTS.md).