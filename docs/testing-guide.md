# Testing Guide — KTM-2000

Маршрутизатор по тестированию. Детали — в AGENTS.md рядом с кодом.

## Уровни тестирования

| Уровень | Инструмент | Канон |
|---------|------------|-------|
| Backend | pytest | [`backend/tests/AGENTS.md`](../backend/tests/AGENTS.md) |
| Frontend unit | Vitest | [`frontend/AGENTS.md`](../frontend/AGENTS.md) |
| E2E | Playwright | [`frontend/e2e/AGENTS.md`](../frontend/e2e/AGENTS.md) |

## Быстрый старт

```bash
npm run test:pytest            # backend, параллельно, изолированная per-run БД (по умолчанию)
npm run test:pytest:full       # backend, серийно
npm --prefix frontend run test    # Vitest
npm --prefix frontend run test:e2e  # Playwright
```

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

`test:db:down` — только ручная остановка; тестовые прогоны его не вызывают.

Тестовая БД: `infra/compose/docker-compose.test.yml` (контейнер общий, run-DB
эфемерные). Подробности изоляции, правила написания тестов, Windows warning →
[`backend/tests/AGENTS.md`](../backend/tests/AGENTS.md).