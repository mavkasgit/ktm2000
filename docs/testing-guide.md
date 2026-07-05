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
npm run test:pytest:fast          # backend, параллельно (рекомендуется)
npm --prefix frontend run test    # Vitest
npm --prefix frontend run test:e2e  # Playwright
```

## npm-скрипты backend

| Команда | Назначение |
|---------|------------|
| `npm run test:pytest:fast` | Параллельный прогон всех тестов |
| `npm run test:pytest:mon` | Только изменённые (testmon) |
| `npm run test:pytest:lf` | Только упавшие |
| `npm run test:pytest` | Полный прогон в один поток |
| `npm run test:db:up` / `test:db:wait` | Поднять тестовый Postgres (:5212) |

Тестовая БД: `infra/compose/docker-compose.test.yml`.

Подробности изоляции, правила написания тестов, Windows warning → [`backend/tests/AGENTS.md`](../backend/tests/AGENTS.md).