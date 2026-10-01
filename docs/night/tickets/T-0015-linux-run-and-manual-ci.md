# T-0015 — Набор на Linux: прогон проверен, ручной CI-джоб добавлен

- **Категория:** CI-эффективность / повторяемость окружения
- **Статус:** DONE (коммит см. `JOURNAL.md`)
- **Дата:** 2026-10-01, цикл 4
- **Файлы:** `.github/workflows/backend-tests.yml` (новый)
- **Связь:** B-0001

## Проблема и доказательство

Единственный workflow репозитория (`migrations.yml`) запускает только
миграции/сиды/манифест — полный pytest-набор в CI **не запускается ни разу**.
При этом неизвестно главное, что нужно для решения: переносим ли набор на
Linux вообще. Известно было только то, что он зелёный на Windows.

## Что сделано: сначала измерение

Набор прогнан в Linux-контейнере против того же образа Postgres (сервис
`ktm2000-test_default`, алиас `postgres`, внутренний порт 5432):

```
docker run --rm --network ktm2000-test_default \
  -v "<worktree>:/app" -w /app \
  -e TEST_DB_HOST=postgres -e TEST_DB_PORT=5432 \
  python:3.12-slim bash -lc "
    pip install -q -r backend/requirements.txt
    python scripts/test-db.py create ktm2000_test_abcdefabcdef
    cd backend && TEST_RUN_ID=abcdefabcdef TEST_DB_NAME=… TEST_DATABASE_URL=… \
      python -m pytest -q -p no:cacheprovider -n 4 --dist loadfile"
```

Результат (`logs/linux-run.log`): **`1951 passed, 0 failed, 43 warnings`** за
**189.42s (3:09)** — те же 1951 теста, что и на Windows, ни одного
платформенного падения; на Linux даже быстрее (Windows: 234s).

Самые долгие тесты на Linux — те же: `test_rerun_with_reset_replaces_previous_demo`
(55.7s), `test_route_run_leaves_a_live_queue_on_all_three_sections` (27.3s),
далее миграционные (10–16s). То есть блокер `T-0001` (продуктовый сидер) — тоже
единственный, и он не про платформу.

## Изменение

`.github/workflows/backend-tests.yml` — **ручной** джоб (`workflow_dispatch`):

- блок сервиса Postgres **идентичен** уже существующему `migrations.yml`
  (проверено сравнением YAML: `services identical: True`) — то есть wiring
  взят из работающего workflow, а не сочинён заново;
- шаги — ровно те команды, что прошли в контейнере: `pip install -r
  backend/requirements.txt`, `scripts/test-db.py create`, pytest с
  `-n 4 --dist loadfile`, уборка run-DB через `trap ... EXIT`;
- триггер только ручной: включение в push/PR — решение про минуты CI
  (B-0001), поэтому по умолчанию джоб ничего не стоит.

## Граница: что НЕ затронуто

- Продуктовый код, тесты, `conftest.py`, launcher — не менялись.
- Новых зависимостей нет: `pytest`, `pytest-asyncio`, `pytest-xdist` уже в
  `backend/requirements.txt`.
- Существующий `migrations.yml` не тронут; push/PR-триггеры не добавлены.
- Изоляция прогона та же: run-DB создаёт и удаляет `scripts/test-db.py`.

## Критерии готовности (измеримые)

1. YAML валиден (`yaml.safe_load`), ключ `on` — только `workflow_dispatch`.
2. Блок сервиса Postgres побайтово равен блоку из `migrations.yml`.
3. Команды джоба проверены локально в Linux-контейнере: `1951 passed, 0 failed`.
4. Диффа — один новый файл в `.github/workflows/`.

## Ограничение (честно)

Сам факт запуска на GitHub Actions отсюда не проверить: раннер и `services`
проверяются только первым ручным запуском. Риск ограничен тем, что джоб
ручной — при любой ошибке он ничего не блокирует и не влияет на `main`.

## План отката

`git revert <commit>` (удаление одного файла).

## Артефакты

- `logs/linux-run.log` — полный вывод прогона в контейнере.
