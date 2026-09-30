# T-0004 — Тест изоляции стенда падает в чистом дереве: требует локальный `.env.dev`

- **Категория:** повторяемость окружения / изоляция
- **Статус:** PLANNED → IN_PROGRESS
- **Дата:** 2026-10-01, цикл 1
- **Файл (не в denylist):** `backend/tests/test_e2e_stand.py`

## Проблема и доказательство

Во всех трёх прогонах baseline (и в 5-прогонной серии) падает ровно один тест:

```
FAILED tests/test_e2e_stand.py::test_stand_database_is_not_the_dev_database
FileNotFoundError: [Errno 2] No such file or directory:
  'C:\Users\LogoPrint\VibeCoding\ktm2000-night\.env.dev'
```

`backend/tests/test_e2e_stand.py:18` жёстко читает `REPO_ROOT/.env.dev`, а этот
файл **gitignored** (`.gitignore:9 .env.*`) и создаётся руками по
`docs/GETTING_STARTED.md:29` (`cp .env.example .env.dev`). Значит, в любом
чистом клоне, в git-worktree и в CI тест падает не из-за продукта, а из-за
отсутствия локального файла. Побочный эффект: набор тестов никогда не бывает
полностью зелёным в изолированном дереве, и «1 failed» приходится каждый раз
объяснять.

При этом в репозитории **уже есть** конвенция для этого случая —
`scripts/e2e-db.py:67-68`:

```python
# Подстраховка на случай, если `.env.dev` локально отсутствует или переименован.
FALLBACK_DEV_DB_NAMES = {"ktm2000_dev"}
FALLBACK_DEV_ENDPOINTS = {("localhost", 5440), ("127.0.0.1", 5440)}
```

и `dev_databases()` (`scripts/e2e-db.py:149-165`): набор dev-баз/endpoint'ов
начинается с fallback'а и **дополняется** содержимым `.env.dev`, если файл
есть. Тест же этой конвенции не следует — отсюда падение.

## План изменений

Только `backend/tests/test_e2e_stand.py`:

1. Ввести ту же пару констант-fallback (с ссылкой на `scripts/e2e-db.py`, чтобы
   не заводить вторую конвенцию) и функцию
   `_dev_targets(dev_env_file: Path = DEV_ENV_FILE) -> tuple[set[str], set[tuple[str, int]]]`,
   повторяющую семантику `dev_databases()`:
   - старт с fallback-набора;
   - если файла нет — вернуть fallback;
   - если есть `DATABASE_URL` — добавить имя БД и endpoint из DSN;
   - иначе, если есть `POSTGRES_DB` / `DEV_POSTGRES_PORT` — добавить их.
2. В самом тесте заменить `dev = urlparse(_dsn_from_env_file(DEV_ENV_FILE))`
   на проверку «DSN стенда не попадает в dev-набор»:
   - имя БД стенда непустое;
   - имя БД стенда ∉ dev-имён;
   - endpoint стенда ∉ dev-endpoint'ов.
3. Добавить три юнит-теста новой функции на `tmp_path` (файла нет; файл с
   `DATABASE_URL`; файл только с `POSTGRES_DB`+`DEV_POSTGRES_PORT`) — новые
   ветки логики должны быть покрыты, а не «проверены глазами».

## Граница: что НЕ будет затронуто

- Продуктовый код и `scripts/e2e-db.py` — не трогаются (fallback в скрипте уже
  есть; тест лишь повторяет его семантику).
- Ни один тест не удаляется и не скипается: вместо `skip` тест получает
  fallback-набор и **проверяет те же три свойства**, что и раньше.
- Ассерты не ослабляются: при наличии `.env.dev` в наборе одновременно и
  fallback, и реальные значения dev-конфига (проверок становится больше, не
  меньше).
- `docs/GETTING_STARTED.md` и `.env*` — не трогаются.

## Критерии готовности (измеримые)

1. В чистом worktree (`.env.dev` отсутствует) тест `test_stand_database_is_not_the_dev_database`
   **проходит** — до правки падал `FileNotFoundError` (зафиксировано в
   `logs/baseline-run1..3.log`).
2. Полный прогон: было `1 failed, 1941 passed` → стало `0 failed, 1941 + N passed`
   (N — число новых юнит-тестов; ни один прежний тест не пропал).
3. Предупреждений не становится больше (45 → ≤45).
4. Диффа вне `backend/tests/` нет.

## План отката

`git revert <commit>`; изменение обособлено в одном файле тестов.

## Замеры (до/после)

| Замер | До | После |
|---|---|---|
| `test_stand_database_is_not_the_dev_database` | FAILED (FileNotFoundError) | — |
| Полный прогон | 1 failed, 1941 passed | — |
