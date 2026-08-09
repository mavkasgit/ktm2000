# Изоляция тестовых БД — launcher владеет per-run run-DB

## Статус

accepted

## Решение

`npm run test:pytest` — единственная точка входа в тесты. `scripts/test-run.ps1`
генерирует `RUN_ID` (12 hex), создаёт **эфемерную** БД `ktm2000_test_<runid>`,
выставляет `TEST_RUN_ID` / `TEST_DB_NAME` / `TEST_DATABASE_URL`, запускает pytest
и в `finally` дропает **только свою** БД. `conftest.py` run-DB не создаёт и не
удаляет — только подключается и изолирует схемы `t_<uuid8>` на модуль.

PostgreSQL-контейнер — **общая инфраструктура**, живёт независимо от тестового
прогона; `docker compose down`/`stop` прогоном не выполняется. Orphan run-DB
(убитый прогон) убирает отдельная команда `npm run test:db:cleanup` по TTL (24h)
через sidecar-таблицу владельцев `ktm2000_test_owner` (`created_at`,
`last_seen_at`, индекс, ownership-проверка перед DROP, guard на активные
коннекты). Имена БД строго валидируются `^ktm2000_test_[0-9a-f]{12}$`.

## Почему

Раньше конфигурация существовала в двух местах: npm-скрипты дёргали общую БД
`ktm2000_test`, а `conftest.py` поверх неё сам создавал run-DB `ktm_test_w_*`
и свипал чужие «устаревшие» БД в `pytest_sessionstart`. При параллельных
агентах это давало флаки: один прогон мог дропнуть БД другого в момент, когда
у той не было активных коннектов (`InvalidCatalogNameError`). Изоляция стала
свойством **команды**, а не дисциплиной агента: каждый запуск сам получает
собственную БД и не пересекается с остальными.

## Последствия

- `conftest.py` избавлен от владения lifecycle (CREATE/DROP/cleanup ушли);
  там остались только module-schema изоляция и fixtures.
- При установленном `TEST_DATABASE_URL` имя БД обязано матчить regex launcher'а.
  Ручной serial `pytest` без env работает на статичной `ktm2000_test`;
  параллельный `pytest -n auto` без launcher — ошибка.
- `test:db:cleanup-legacy` — одноразовая уборка старых `ktm_test_*`
  (dry-run → `--apply`), после миграции удаляется.
