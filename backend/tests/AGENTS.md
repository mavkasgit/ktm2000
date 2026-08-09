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

### Orphan cleanup

Run-DB, осиротевшая из-за убитого прогона, убирается отдельной командой
(`npm run test:db:cleanup`, TTL 24h). В обычный прогон cleanup не встроен.

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
| `npm run test:pytest` | Параллельный прогон (по умолчанию, ~3 мин) |
| `npm run test:pytest:fast` | Алиас `test:pytest` |
| `npm run test:pytest:full` | Полный прогон в один поток |
| `npm run test:pytest:mon` | Только изменённые тесты (testmon) |
| `npm run test:pytest:lf` | Только упавшие в прошлый раз |
| `npm run test:db:cleanup` | Уборка orphan run-DB по TTL (24h) |

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