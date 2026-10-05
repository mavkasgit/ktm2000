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
npm run db:seed                # Справочники (участки, маршруты, шаблоны импорта)
npm run db:seed:packing-demo   # Демо-доска «Участков»: два набора планов (упаковочный + «План подготовительного участка») на шести участках, парные артикулы, их непарный вариант и незакрытые позиции + дневные планы
npm run db:snapshot -- dump <label> / restore <name>   # Слепок dev-БД в data/backups/snapshots
npm run test:pytest            # Тесты backend (параллельно, дефолт; slow пропускаются)
npm run test:pytest:full       # Полный прогон в один поток
npm run test:pytest:mon        # Только изменённые тесты
npm run test:pytest:lf         # Только упавшие тесты
npm run test:e2e              # Playwright на ОТДЕЛЬНОМ стенде: БД — клон шаблона ktm2000_e2e_template (Postgres :5441), порты — свободные, каждый прогон свои
npm run test:db:cleanup        # Уборка осиротевших тестовых БД (TTL 24h)
```

Порты dev: Postgres `5440`, backend `8012`, frontend `5172`.
Стенд E2E (`npm run test:e2e`) не делит их: Postgres `5441`, хранилище
`data/storage-e2e` (`.env.e2e`). Базу прогон тоже не делит ни с кем: `e2e:prep`
держит шаблон `<база>_template` (миграции + сиды, пересобирается при
расхождении с репозиторием) и клонирует его под прогон
(`<база>_run_<stamp>_<run-id>`), а после прогона клон сносится. Порты backend и
frontend стенд **не имеет** — [`frontend/scripts/run-e2e.mjs`](frontend/scripts/run-e2e.mjs)
берёт два свободных порта у ОС на каждый прогон, поэтому осиротевший стек
прошлого прогона не может сорвать следующий. Прогон против уже поднятого
стека — `PW_REUSE_STACK=1` вместе с `E2E_API_URL`/`PLAYWRIGHT_TEST_BASE_URL`
(тогда обёртка их не трогает).

### Стенды: e2e агент запускает сам, devstack — человек

**e2e агент запускает сам.** Стенд изолирован: клон своей базы-шаблона из
`.env.e2e` (у каждого репозитория своё имя), порты выдаёт ОС на каждый прогон,
стек поднимает и убирает сам Playwright. Числом одновременных прогонов на
машине управляет счётный семафор (`E2E_MAX_PARALLEL_RUNS`, по умолчанию 2;
слоты вне репозитория, поэтому видны всем worktree). Условия, при которых
прогон что-то доказывает (слот получен, чужого WIP в спеке нет, `CI` не задан,
`--retries=0`, в отчёте SHA/команда/workers/retries) — в
[`frontend/e2e/AGENTS.md`](frontend/e2e/AGENTS.md), разделы «Механика БД:
шаблон, клон, уборка» и «Кто запускает e2e».

**devstack агент не поднимает:** ни `npm run dev`, ни `db:up`/`db:migrate`,
ни установку зависимостей в `.venv`, ни `dev:kill`. Причина: запуск занимает
минуты и всё равно упирается в окружение (venv без зависимостей, занятые
порты, чужая `DATABASE_URL`) — агент в этом только тратит время и лог, а не
проверяет задачу.

Нужна проверка вживую — спроси пользователя одной строкой, что поднять, и
заодно дай команду запуска (он и так знает, но это экономит ему раунд):

| Что нужно | Попросить запустить | Что сделать агенту |
|-----------|--------------------|-------------------|
| Посмотреть правку UI в браузере | `npm run dev` (или уже поднятый стенд) | Ждать подтверждения, затем `xd://browser` |
| Прогнать e2e | — | Запускать самому: `npm --prefix frontend run test:e2e:ui` (клон своей БД, слот семафора) |
| Прогнать backend-тесты | — | Запускать самому: это изолированная БД, чужих портов не занимает |

Если стенд уже поднят пользователем — проверять можно сразу, ничего не
запуская.

### Если dev-стек не поднимается или «падает сам»

| Симптом | Причина | Что делать |
|---------|---------|-----------|
| Страница по LAN-IP не открывается, `localhost` отвечает | Порт держит чужой процесс, слушающий только `127.0.0.1` | `npm run dev:ports` (кто держит) → `npm run dev:kill` |
| Vite: `Port 5172 is already in use` и уходит | Порт занят другим vite | `npm run dev:kill`, затем `npm run dev` |
| `alembic` / backend: `ConnectionRefusedError` при живом Postgres | В окружении осталась чужая `DATABASE_URL` (напр. на `:5432` вместо `:5440`) | Env-файл — источник правды: `.env.dev` перекрывает окружение сам. Если ошибка в чужом окружении — снять `DATABASE_URL` |
| Весь стек умер после правки `.py` | — | Не должен: `npm run backend` ведёт `backend/scripts/dev_server.py` (рестарт только рабочего процесса, скоуп `app/`, битый синтаксис не роняет API). Если упало — пришлите лог |

Детали реализации → [`backend/AGENTS.md`](backend/AGENTS.md) («Dev-режим») и [`docs/agent-registry.md`](docs/agent-registry.md) («Порты»).

## Тесты

Канон pytest → [`backend/tests/AGENTS.md`](backend/tests/AGENTS.md).

- Каждый прогон идёт через launcher `scripts/test-run.ps1`: он создаёт свою БД `ktm2000_test_<runid>` и в `finally` дропает только её. Параллельные прогоны не видят и не удаляют чужие БД.
- При нескольких параллельных агентах задавайте `PYTEST_NUM_WORKERS` (например `4`): иначе каждый `-n auto` захватит все ядра и машина перестанет отвечать.
- Отдельный тест — через launcher (изолированная БД): `npm run test:pytest -- -k shopflow`.
- Отладка без изоляции (serial, общая статичная БД, только отладка): `cd backend && python -m pytest tests/test_shopfloor_api.py::test_name -v`.
- `test:db:down` из тестовых launcher'ов не использовать.

## Разведка

- Поиск кода и символов — **CodeGraph**, когда в сессии есть `codegraph_explore` (MCP подключён, строка 97). Инструмента нет — работайте обычным поиском по файлам, это полноценная замена для точечных вопросов; CodeGraph выигрывает на кросс-файловых разведках («кто вызывает», «что тянет»), а не на поиске строки.
- Внешние best practices — **Exa MCP** (`web_search_exa` / `web_search`).
- Полная матрица MCP → [`docs/agent-registry.md`](docs/agent-registry.md).
- После значимых правок кода: `npx @colbymchenry/codegraph sync`. Индекс стареет незаметно — ответы по коду, изменённому после последнего `sync`, берутся из устаревшей выдачи, и это выглядит как правда. Сверить возраст: индекс лежит в `.codegraph/codegraph.db`, если он старше последнего коммита — `sync` ещё не делали.
- Индекс CodeGraph локальный и не в git (`.codegraph/` в `.gitignore`), поэтому на новой машине/клоне — один раз `npx @colbymchenry/codegraph init -y`, и только потом `sync`. `sync` не инициализирует: без индекса он падает с `CodeGraph not initialized`.
- MCP-сервер ставится отдельно и один раз на harness: `npx @colbymchenry/codegraph install -t <агент> -l global`. Пока он не установлен, `codegraph_explore` в сессии не будет — это состояние, а не правило; CLI (`npx @colbymchenry/codegraph query <символ>`) работает и без MCP, даёт тот же индекс.

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

## Логи контейнеров

Каждый сервис в `infra/compose/docker-compose.prod.yml` обязан объявлять потолок лога:

```yaml
logging:
  driver: json-file
  options:
    max-size: "20m"
    max-file: "3"
```

Потолок — около 60 МБ на контейнер: без него json-лог растёт неограниченно. Новый сервис
в compose — сразу с этим блоком.

Прод ktm2000 крутится на рабочей машине, где хостового logrotate нет, — здесь блок
в compose единственная защита. На прод-сервере дополнительно стоит
`/etc/logrotate.d/docker-containers` (`size 200M`, `rotate 3`, `compress`, `copytruncate`).

`docker logs` отдаёт и ротированные файлы, поэтому его вывод больше текущего файла —
это не протечка потолка.

## Agent skills

### Issue tracker

Issues are tracked in GitHub Issues for `mavkasgit/ktm2000` via the `gh` CLI. See `docs/agents/issue-tracker.md`.

### Triage labels

Default five-role vocabulary (needs-triage, needs-info, ready-for-agent, ready-for-human, wontfix). See `docs/agents/triage-labels.md`.

### Domain docs

Single-context layout — one `GLOSSARY.md` + `docs/adr/` at root. See `docs/agents/domain.md`.
