# Project Overview — KTM-2000

## Описание

**KTM-2000** — локальная система производственного планирования и контроля для цехового производства. Управление участками, планы, импорт Excel, технологические карты, складской ledger, бэкапы.

Монорепозиторий: frontend + backend + PostgreSQL в Docker.

Установка → [GETTING_STARTED.md](GETTING_STARTED.md). AI-агенты → [AGENTS.md](../AGENTS.md).

## Стек технологий

| Слой | Технология | Версия |
|------|-----------|--------|
| Backend | Python + FastAPI | 3.12+ |
| ORM | SQLAlchemy + Alembic | async `asyncpg` |
| Database | PostgreSQL | 15 (Docker) |
| Frontend | React + TypeScript | 19+ (Vite) |
| Styling | Tailwind CSS + shadcn/ui | — |
| Backend tests | pytest + xdist + testmon | — |
| E2E | Playwright | ^1.59.1 |

## UI-модули

| Маршрут | Назначение |
|---------|------------|
| `/` | Обзор (dashboard) |
| `/references/*` | Справочники: сырьё, продукция, ГХП, техкарты, маршруты |
| `/planning` | Планирование производства |
| `/execution` | Контроль выполнения |
| `/section-tasks` | Участки (shopfloor) |
| `/transfers` | Передачи между участками |
| `/spg` | ГХП (снимок) |
| `/audit-logs` | Журнал действий |
| `/settings/*` | Настройки, бэкапы, пользователи |

## Дерево каталогов

```
ktm2000/
├── AGENTS.md              # Bootstrap для AI-агентов
├── backend/
│   ├── app/
│   │   ├── api/routes/    # Эндпоинты
│   │   ├── models/        # ORM
│   │   ├── services/      # Бизнес-логика
│   │   ├── stock/         # Stock Ledger
│   │   ├── transfers/     # Передачи
│   │   └── seeds/         # Демо-данные
│   ├── migrations/        # Alembic
│   └── tests/             # pytest (канон → tests/AGENTS.md)
├── frontend/
│   ├── src/               # FSD: app, features, entities, shared
│   └── e2e/               # Playwright
├── infra/compose/         # docker-compose (dev, test, prod)
├── scripts/               # Вспомогательные скрипты
└── docs/                  # Документация
```

## Домен Stock Ledger

Единый источник правды — `StockTransaction` (append-only). Legacy `SpgRemainder`, `Movement` удалены.

| Сущность | Таблица | Назначение |
|----------|---------|------------|
| `Location` (= `Section`) | `sections` | Локация материала; `type`: `production`, `raw_stock`, `wip_stock`, `finished_stock`, `scrap`, `quarantine` |
| `StockTransaction` | `stock_transactions` | Ledger: from/to location, quantity, reason, quality_state |
| `StockBalance` | `stock_balances` | Кэш баланса по (product, location, quality_state) |
| `WorkTask` | `work_tasks` | План в `planned_quantity`; выполнение — из транзакций |
| `Transfer` | `transfers` | Бизнес-lifecycle; 2 StockTransaction; cancel = компенсация |
| `Defect` | `defects` | Обоснование брака; `stock_transaction_id` FK |

Принципы:
1. Ядро хранит факты, UI — политики.
2. Баланс = projection из `StockTransaction`.
3. Append-only: отмена = компенсационная транзакция.
4. API: `/api/stock/*` и `/api/spg/*`.

## Auth / OIDC

Локальная auth (password + OTP) + dual-run OIDC bridge к Authentik (public SPA + PKCE → app JWT).

- Связка: primary `users.authentik_sub`, secondary username/email, optional JIT.
- MES-роли (`users.role`) — app SoT; IdP groups не перезаписывают роль по умолчанию.
- Logout: clear `ktm2000_token` + Authentik end-session при OIDC on.
- Dev: `DEV_BYPASS_AUTH` + magic Bearer `admin` (только dev); prod strict off.

Канон и env → [`docs/auth-oidc.md`](auth-oidc.md).

## Порты

| Окружение | Frontend | Postgres | Backend |
|-----------|----------|----------|---------|
| dev | `5172` | `5202` | `8010` |
| test | `8100` | `5212` | `8010` |
| prod | `8020` | `5432` (внутри Docker) | `8010` |
| E2E CDP | — | — | `9222` |

## Архитектурные решения

1. **FSD на фронтенде** — слои `app` → `features` → `entities` → `shared`; без cross-imports между features.
2. **Async backend** — все операции БД через `AsyncSession`.
3. **Docker только для БД в dev** — backend/frontend на хосте для hot reload.
4. **Playwright CDP** — E2E через Chrome `--remote-debugging-port=9222`.