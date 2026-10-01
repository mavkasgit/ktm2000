# Backend Tests (pytest)

Каноническое руководство по pytest в KTM-2000. Стек: **pytest**, **pytest-xdist**, **pytest-testmon**.

## Изоляция базы данных (run-DB + module schema)

Запуск всегда идёт через launcher `scripts/test-run.ps1`, который **владеет
жизненным циклом run-DB**:

1. Генерирует `RUN_ID` (12 hex), создаёт **`ktm2000_test_<runid>`**, выставляет
   `TEST_RUN_ID` / `TEST_DB_NAME` / `TEST_DATABASE_URL`.
2. Запускает pytest и в `finally` **гарантированно дропает только свою БД**.

Каждый запуск получает собственную БД; параллельные прогоны не видят и не
удаляют чужие БД. `conftest.py` run-DB **не создаёт и не удаляет** — только
подключается к той, что дал launcher.

> При нескольких параллельных агентах задавайте `PYTEST_NUM_WORKERS` (например
> `4`) — иначе каждый `-n auto` захватит все ядра. Изоляция гарантируется
> архитектурой; лимит воркеров защищает саму машину от перегрузки.

Интерпретатор прогона задаётся явно переменной `TEST_PYTHON` (по умолчанию —
`python` из `PATH`); launcher проверяет, что он запускается, и печатает
выбранный в шапке прогона.

Параллельный прогон идёт с `--dist loadfile`: **модуль целиком одному
воркеру**. Это не косметика, а следствие изоляции «схема на модуль»: при
дефолтном `--dist load` тесты одного модуля разъезжаются по воркерам, и
`Base.metadata.create_all()` для модуля выполняется на каждом из них. Замер
(3+3 прогона, чередование, `PYTEST_NUM_WORKERS=4`): `load` — 370.7 / 372.2 /
367.7s, `loadfile` — 259.4 / 256.6 / 256.3s (**−31%**), сумма `setup`
327s → 287s, результаты идентичны (`1945 passed`). Свой `--dist` в аргументах
имеет приоритет над этим дефолтом.

Внутри run-DB:

1. **Схема на модуль**: одна схема `t_<uuid8>` на модуль,
   `Base.metadata.create_all()` при старте модуля. В launcher-режиме схема
   **не дропается** (run-DB падает целиком в `finally` launcher'а;
   per-module `DROP SCHEMA CASCADE` ≈ 0.25s × модуль — чистые расходы).
   В ручном режиме на статичной `ktm2000_test` схема дропается в teardown,
   чтобы не копилась.
2. **Транзакция на тест** (`function scope`): каждый тест в SAVEPOINT;
   по завершении — `rollback`.
3. **Сброс sequence users**: перед каждым тестом
   `ALTER TABLE users ALTER COLUMN id RESTART WITH 1` — `system_user` всегда `id = 1`.

Режим: `PYTEST_DB_MODE=hybrid` (единственный поддерживаемый).

### Контракт `TEST_DATABASE_URL`

- **Установлен (launcher)**: имя БД обязано матчить `^ktm2000_test_[0-9a-f]{12}$`,
  иначе pytest падает до старта.
- **Не установлен (ручная отладка)**: разрешён только **serial** pytest на
  статичной `ktm2000_test`; параллельный `pytest -n auto` без launcher — ошибка.

### Storage-каталог тестов

Тесты пишут файлы только в `%TEMP%\ktm2000_pytest_storage_<TEST_RUN_ID>`
(`conftest.py` выставляет `STORAGE_ROOT` до импорта приложения). Каталог **свой
у каждого прогона** и удаляется по завершении — параллельные прогоны не делят
файлы, мусор не копится.

### Проверка нестабильности (flaky)

Правка, которая может задеть тайминги, изоляцию или порядок, проверяется серией
прогонов, а не одним. Рецепт, которым пользовались при замерах (Windows,
`PYTEST_NUM_WORKERS=4`):

```bash
for i in 1 2 3 4 5; do
  PYTEST_NUM_WORKERS=4 npm run test:pytest -- -q --durations=0 \
    > "logs/flaky-$i.log" 2>&1
done
grep -h "^FAILED" logs/flaky-*.log | sort | uniq -c   # один и тот же набор?
grep -h "passed" logs/flaky-*.log | tail -5           # число тестов не плывёт?
```

Признак стабильности — **одинаковый набор `FAILED` и одинаковое число
`passed`** во всех прогонах; разброс wall time в пределах ~±7% — это шум машины
(dev-стек, антивирус, планировщик), а не флейк. Замер 2026-10-01: 5 прогонов
baseline и 3 прогона после правок — наборы совпали полностью.

Пара «прогон без правок и прогон с правкой» сравнивается по числам, а не по
ощущению: `--durations=0` даёт и самые медленные тесты, и суммы фаз
(`call`/`setup`/`teardown`).

### Orphan cleanup

Run-DB, осиротевшая из-за убитого прогона, убирается отдельной командой
(`npm run test:db:cleanup`, TTL 24h) — та же команда по TTL убирает и старые
каталоги storage тестов (`ktm2000_pytest_storage*` в `%TEMP%`), оставшиеся от
прерванных прогонов. В обычный прогон cleanup не встроен.
БД, оставленная прогоном с `--keep-db` (для разбора падения), сохраняет
owner-строку — её убирает либо `python scripts/test-db.py drop <db>` сразу,
либо тот же TTL-cleanup потом.

Базы миграционных тестов (`ktm_mig_<10 hex>` — их создают
`test_migrations.py` и `test_hanger_norm_key_migration_218.py` напрямую, без
owner-строки) в TTL-уборку не попадают: `cleanup` сканирует только
`ktm2000_test_%`. Осиротевшую после прерванного прогона убирает
`python scripts/test-db.py drop --force <db>` (отказывает, если у базы есть
активные соединения, и на служебных именах `postgres`/`template0`/`template1`).

Подробности реализации: [`conftest.py`](conftest.py), [`scripts/test-run.ps1`](../../scripts/test-run.ps1).

## Правила написания тестов

- **Динамические ID** — не полагайтесь на `id = 1, 2, 3`; читайте `product.id`, `task.id` из объекта.
- **Изоляция транзакций** — `session.commit()` в тесте фиксирует только savepoint, не основную транзакцию.
- **Не мутируйте module-scope данные** — общие фикстуры `scope="module"` только для чтения.
- **Integrity helper** — после Transfer/StockTransaction:
  ```python
  from tests.test_integrity_invariants import assert_no_invariants_violations
  await assert_no_invariants_violations(session, context="your-context")
  ```

## Команды (из корня проекта)

| Команда | Назначение |
|---------|------------|
| `npm run test:pytest` | Параллельный прогон (по умолчанию, ~4.5 мин при `PYTEST_NUM_WORKERS=4` — замер 2026-10-01) |
| `npm run test:pytest:fast` | Алиас `test:pytest` |
| `npm run test:pytest:full` | Полный прогон в один поток |
| `npm run test:pytest:mon` | Только изменённые тесты (testmon) |
| `npm run test:pytest:lf` | Только упавшие в прошлый раз |
| `npm run test:db:cleanup` | Уборка orphan run-DB по TTL (24h) |
| `npm run test:hygiene` | Report-only отчёт по мёртвым импортам в тестах (`scripts/check-test-imports.py`, без линтера) |

Отдельный тест через launcher (изолированная БД):
`npm run test:pytest -- -k shopflow`

Отладка вручную (serial, общая статичная БД, без изоляции):

```bash
npm run test:db:up && npm run test:db:wait
cd backend
pytest -v -k shopfloor
pytest tests/test_shopfloor_api.py::test_shopfloor_over_issue_rejected -v
```

> [!WARNING]
> На Windows не используйте пайплайны `2>&1 | head` — символ `2` может быть воспринят pytest как путь к файлу. Перенаправляйте в файл: `pytest tests/ -v > out.txt 2>&1`.

Профилирование: `backend/pytest.ini` выводит 10 самых медленных тестов (`--durations=10`).