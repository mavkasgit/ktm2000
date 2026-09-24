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
| Frontend | React + TypeScript | 18.3 (Vite) |
| Styling | Tailwind CSS + shadcn/ui | — |
| Backend tests | pytest + xdist + testmon | — |
| E2E | Playwright | ^1.60.0 |

## UI-модули

| Маршрут | Назначение |
|---------|------------|
| `/` | Обзор (dashboard) |
| `/references/*` | Справочники: сырьё, продукция, ГХП, маршруты |
| `/planning` | Планирование производства |
| `/execution` | Контроль выполнения |
| `/section-tasks` | Участки (shopfloor) |
| `/transfers` | Передачи между участками |
| `/spg` | ГХП (снимок) |
| `/audit-logs` | Журнал действий |
| `/reversal` | Журнал действий (реверс) |
| `/settings/*` | Настройки, бэкапы, пользователи |
| `/settings/users` | Пользователи (только admin) |
| `/settings/employees` | Сотрудники (только admin) |
| `/settings/dev` | Dev-настройки (только admin) |

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
│   ├── alembic/           # Alembic (миграции в versions/)
│   └── tests/             # pytest (канон → tests/AGENTS.md)
├── frontend/
│   ├── src/               # FSD: app, features, entities, shared
│   │   └── modules/       # Переносимые модули (notifications, user-settings); host-адаптеры из features через alias `@/modules/*`
│   └── e2e/               # Playwright
├── infra/compose/         # docker-compose (dev, test, prod)
├── scripts/               # Вспомогательные скрипты
└── docs/                  # Документация
```

## Домен Stock Ledger

Единый источник правды — `StockTransaction` (append-only). Legacy `SpgRemainder`, `Movement` удалены.

| Сущность | Таблица | Назначение |
|----------|---------|------------|
| `Location` (= `Section`) | `sections` | Локация материала; `type`: `production`, `raw_stock`, `wip_stock`, `finished_stock`, `scrap`, `terminal` |
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

## Переход на нормальные и сырьевые длины

- Линейный артикул хранит реестр пар `normalLength` / `rawLength`. План, работа,
  передачи, ledger и раскрой пилы используют только `normalLength`; `rawLength`
  влияет только на автоматическое N на подвесе.
- Миграции `059`–`060` переносят старые значения без угадывания `2750 → 2700`.
  Перед переходом нужно разрешить конфликты типовых размеров вручную.
- Планы с `length_model_version = 1` доступны только для чтения. Для продолжения
  работы переимпортировать исходный Excel новым планом; вручную менять версию
  или SQL-подменять геометрию запрещено.
- Остатки старых размеров переоцениваются физической сверкой и штатными
  операциями движения. Автоматической замены размера остатка нет.

Подробный контракт импорта и read-only ошибки — в
[`plan-import-spec.md`](plan-import-spec.md).

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
| dev | `5172` | `5440` | `8012` |
| test | `8100` | `5441` | `8000` (внутри контейнера) |
| prod | `8082` (nginx, наружу) | `5432` (внутри Docker) | `8000` (внутри Docker) |

## Архитектурные решения

1. **FSD на фронтенде** — слои `app` → `features` → `entities` → `shared`; без cross-imports между features.
2. **Async backend** — все операции БД через `AsyncSession`.
3. **Docker только для БД в dev** — backend/frontend на хосте для hot reload.
4. **Playwright (bundled Chromium)** — E2E-проекты `ui-e2e` (`@ui`) и `smoke` (`@smoke`) на штатном Chromium из Playwright; `webServer` в конфиге отключён, dev-окружение поднимается вручную.