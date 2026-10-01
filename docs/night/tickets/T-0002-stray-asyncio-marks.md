# T-0002 — Снять 2 предупреждения pytest-asyncio: лишний module-level маркер

- **Категория:** гигиена конфигов тестов / чистота вывода
- **Статус:** DONE (коммит `d07f2e6`)
- **Дата:** 2026-09-30, цикл 1
- **Файлы (не в denylist):**
  - `backend/tests/test_plan_endpoints_auth.py`
  - `backend/tests/test_stock_remainder_import.py`

## Проблема и доказательство

В `baseline-run1.log` (1941 passed, 45 warnings) два предупреждения говорят
прямо:

```
PytestWarning: The test <Function test_plan_import_route_matrix_is_complete> is
marked with '@pytest.mark.asyncio' but it is not an async function.
PytestWarning: The test <Function test_parse_operations_from_comment_extracts_names> is
marked with '@pytest.mark.asyncio' but it is not an async function.
```

Источник — не декоратор на функции, а module-level маркер:

- `backend/tests/test_plan_endpoints_auth.py:30` → `pytestmark = pytest.mark.asyncio`
- `backend/tests/test_stock_remainder_import.py:33` → `pytestmark = pytest.mark.asyncio`

Скан всех тестов: module-level `pytestmark = pytest.mark.asyncio` стоит в 54
файлах, но синхронных тестов внутри них ровно **два** — те самые. То есть маркер
почти везде безвреден, а предупреждение даёт только эта пара.

Дополнительно: `backend/pytest.ini` содержит `asyncio_mode = auto` — в этом
режиме pytest-asyncio сам помечает корутинные тесты, поэтому module-level
маркер в этих двух файлах **избыточен**.

## План изменений

1. Удалить строку `pytestmark = pytest.mark.asyncio` в двух файлах выше.
2. Ничего больше не трогать: декораторы на async-тестах не нужны (auto-режим),
   тела тестов и ассерты не меняются.

## Граница: что НЕ будет затронуто

- Продуктовый код — не трогается вообще.
- Другие 52 файла с таким маркером — не трогаются (там нет предупреждений;
  массовая зачистка = лишний риск и шум в диффе).
- Ни один тест не удаляется, не скипается и не ослабляется.
- `pytest.ini` — не меняется.

## Критерии готовности (измеримые)

1. До: прогон двух файлов даёт **2** предупреждения `marked with
   '@pytest.mark.asyncio' but it is not an async function`. После: **0**.
2. Число собранных/прошедших тестов в этих файлах не меняется (async-тесты
   продолжают запускаться в auto-режиме).
3. Полный прогон: `passed` не меньше 1941, число warnings падает на 2
   (45 → 43), новых падений нет.
4. Диффа в продуктовой зоне нет: `git diff --name-only` содержит только те два
   файла.

## План отката

`git revert <commit>` (или `git restore` двух файлов) — изменения обособленные,
на поведение не влияют.

## Замеры (до/после)

| Замер | До | После |
|---|---|---|
| warned-тестов в двух файлах | 2 | 0 |
| warnings в полном прогоне | 45 | **43** |
| passed в полном прогоне | 1941 | **1941** (состав тот же) |
| точечный прогон двух файлов | — | `48 passed, 24 warnings`, предупреждений о маркере — 0 |

Прогоны: `logs/verify-T0002-T0005.log` (полный, `1 failed, 1941 passed,
43 warnings in 355.35s`), `logs/T-0002-targeted.log` (два файла).

Дополнительно: в `test_stock_remainder_import.py` вместе с маркером убран
ставший неиспользуемым `import pytest` (проверено `grep -w pytest` — других
упоминаний в файле нет).
