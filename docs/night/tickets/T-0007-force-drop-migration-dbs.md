# T-0007 — БД миграционных тестов нельзя убрать инструментами репозитория

- **Категория:** гигиена тестовой БД / диагностика
- **Статус:** DONE — проверено на живом Postgres
- **Дата:** 2026-10-01, цикл 1
- **Файлы (тестовая зона):** `scripts/test-db.py`, `docs/testing-guide.md`, `backend/tests/AGENTS.md`
- **Связь:** B-0007

## Замеры (проверки)

| # | Проверка | Результат |
|---|---|---|
| 1 | `drop --force ktm_mig_0123456789` (owner-строки нет) | `Dropped test database: ktm_mig_0123456789` |
| 2 | `drop ktm_mig_0123456789` без `--force` | отказ: `Refusing to touch unsafe database name … must match ^ktm2000_test_[0-9a-f]{12}$`, код возврата **1** |
| 3 | `drop --force` при живом соединении с базой | `Skip drop ktm_mig_0123456789: active connections (1)` |
| 4 | то же после закрытия соединения | `Dropped test database` |
| 5 | `drop --force postgres` | отказ: `Refusing to drop protected database 'postgres'` |
| 6 | `drop --force some_random_db` | отказ: `… must match ^ktm2000_test_[0-9a-f]{12}$ or ^ktm_mig_[0-9a-f]{10}$` |
| 7 | обычный прогон (launcher дропает свою run-DB через `drop`) | см. `logs/verify-T0007-control.log` |

Все проверки — на тестовом Postgres (`:5441`), созданные для проверки базы
удалены; чужие осиротевшие базы (`ktm_mig_3c6bbeebaa` и др.) не трогались.

## Побочный эффект

Теперь у человека есть инструмент для ранее неразрешимой задачи:
`python scripts/test-db.py drop --force ktm_mig_3c6bbeebaa` (осталась от
прерванного прогона до этой ночи).

## Проблема и доказательство

1. `scripts/test-db.py:36` — `RUN_DB_PREFIX = "ktm2000_test_"`; `cleanup()`
   сканирует `WHERE datname LIKE 'ktm2000_test_%'` (`:166`).
2. Миграционные тесты создают базы с другим префиксом:
   `tests/test_migrations.py` и `tests/test_hanger_norm_key_migration_218.py`
   — 17 мест `CREATE DATABASE` / 17 `DROP DATABASE`, имена `ktm_mig_<uuid10>`,
   owner-строка не пишется.
3. `drop()` требует owner-строку (`SELECT db_name FROM ktm2000_test_owner WHERE
   run_id = $1`) и на чужой базе печатает `Skip drop …: no matching owner row`;
   плюс `validate_run_db_name()` вообще не примет имя `ktm_mig_*`.

Итог: базу, оставшуюся от прерванного прогона миграционных тестов, нельзя
удалить ни `drop`, ни `cleanup` — только руками через `psql`. В контейнере
`ktm2000-postgres-test` такие базы наблюдались (`ktm_mig_3c6bbeebaa` и др.).

## План изменений

1. `scripts/test-db.py`: новый режим `drop --force <db>`.
   - принимает и `ktm2000_test_<12hex>`, и `ktm_mig_<hex>`;
   - без `--force` поведение прежнее (только своя run-DB по owner-строке);
   - с `--force` требует, чтобы у базы **не было активных соединений**
     (тот же запрос к `pg_stat_activity`, что в `cleanup`), и отказывается
     трогать служебные базы (`postgres`, `template0`, `template1` — константы
     уже есть в `scripts/e2e-db.py`, продублировать с ссылкой);
   - печатает, что именно удалено.
2. `docs/testing-guide.md`: строка про `drop --force` рядом с описанием уборки
   (одно-два предложения).

## Граница: что НЕ будет затронуто

- Продуктовый код и сами тесты (в т.ч. 17 сайтов create/drop в
  `test_migrations.py`) — **не трогаются**: рефакторинг тестов в этот тикет не
  входит (34 сайта, отдельный риск).
- `cleanup` и TTL-логика — не меняются.
- Защита от удаления чужой живой БД сохраняется: `--force` обязателен, активные
  соединения и служебные имена — запрет.

## Критерии готовности (измеримые)

1. `python scripts/test-db.py drop --force ktm_mig_<hex>` удаляет такую базу
   (проверка: `select datname from pg_database` до/после).
2. Без `--force` тот же вызов отказывает с прежним текстом (`no matching owner
   row`) — прежнее поведение сохранено.
3. При активном соединении с целевой базой `--force` отказывает (проверка:
   открыть соединение и убедиться, что база осталась).
4. `drop --force postgres` отказывает.
5. Полный прогон не меняется (`1945 passed, 0 failed`).

## План отката

`git revert <commit>` — изменение в одном скрипте (+ строка документации).

## Возможное продолжение (не в этом тикете)

Регистрация `ktm_mig_*` в owner-таблице из самих миграционных тестов — тогда
TTL-уборка подхватит их автоматически. Требует правки 34 сайтов, поэтому
отдельным тикетом и только по решению человека.
