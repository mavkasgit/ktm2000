# T-0001 — 6 самых медленных тестов дают 53% времени прогона; причина — продуктовый сидер

- **Категория:** скорость
- **Статус:** BLOCKED_NEEDS_HUMAN (нужна правка продуктового кода, ночному агенту запрещена)
- **Дата:** 2026-09-30, цикл 1
- **Файл тестов:** `backend/tests/test_packing_plan_demo_seeder.py` (не в denylist)
- **Горячий код:** `backend/app/seeds/seeders/packing_plan_demo_seeder.py::_run_route_progress` (продуктовая зона → не правил)

## Проблема и доказательство

### 1. Данные `--durations=0` (прогон baseline №1, workers=4, под нагрузкой)

Суммарное время прогона: **384.37s** (`1 failed, 1941 passed`). Шесть тестов
одного файла:

| Тест | call, s |
|---|---|
| `test_rerun_with_reset_replaces_previous_demo` | 83.68 |
| `test_route_run_leaves_a_live_queue_on_all_three_sections` | 45.97 |
| `test_demo_board_carries_each_position_own_operations` | 19.16 |
| `test_prod_guard_fires_before_any_write` | 18.48 |
| `test_demo_seed_releases_all_plan_positions` | 18.47 |
| `test_demo_seed_fills_daily_plans_on_every_demo_section` | 18.39 |
| **итого** | **204.15 (53% прогона)** |

Следующая группа — `test_migrations.py`: 16 тестов, ~150s суммарно
(самый долгий `test_migration_058_product_pair_quantity_norms` — 13.94s).

### 2. Профиль (cProfile, один тест, тишина, scratch run-DB)

Команда:

```bash
python scripts/test-db.py create ktm2000_test_abcdef123456
cd backend
TEST_RUN_ID=abcdef123456 \
TEST_DATABASE_URL="postgresql+asyncpg://ktm2000_user:ktm2000_pass_test@localhost:5441/ktm2000_test_abcdef123456" \
python -m cProfile -o ../docs/night/logs/prof-rerun.prof -m pytest \
  tests/test_packing_plan_demo_seeder.py::test_rerun_with_reset_replaces_previous_demo -q --durations=0
```

Результат: `1 passed, 8 warnings in 100.21s`, профиль — 104.35s,
47 123 124 вызова функций. Разбор (cumtime за один прогон теста):

| Функция | cumtime, s | вызовов |
|---|---|---|
| `test_rerun_with_reset_replaces_previous_demo` | 117.4 | — |
| `app/seeds/seeders/packing_plan_demo_seeder.py:1206 seed_packing_plan_demo` | **114.5** | 57 656 |
| `…:1043 _run_route_progress` | **73.6** | 37 392 |
| `app/seeds/…/plan_generation.py:140 release_batch` | 12.1 | 7 267 |
| `app/seeds/seeders/packing_plan_demo_seeder.py:955 _ensure_source_stock` | 2.9 | 1 672 |
| `app/seeds/seeders/packing_plan_demo_seeder.py:852 _ensure_products` | 1.1 | 631 |
| `run_seed.py:22 run_full_seed` | **0.69** | 386 |

Самые «дорогие» по собственному времени места профиля: ожидание I/O
(`_overlapped.GetQueuedCompletionStatus` — 38.95s) и `WSASend` (2.9s), то есть
время уходит в **round-trip'ы к Postgres**, а не в CPU.

Счётчик запросов: `asyncpg/prepared_stmt.py:254 __do_execute` — **114 194
вызова** на один тест (два вызова сидера + проверки), т.е. ~57 000 SQL-запросов
на один вызов `seed_packing_plan_demo` (~37 000 из них — внутри
`_run_route_progress`). По 2 мс на localhost это и даёт 37s на вызов.

### 3. Что проверено и отвергнуто как оптимизация в тестовой зоне

- **«Поднять общий `run_full_seed` на module scope»** — не даёт ничего:
  профиль показывает `run_full_seed` = **0.69s**, вся стоимость в демо-сидере.
- **Убрать `run_route=True` у медленных тестов** — запрещено регламентом:
  это ослабление проверяемого поведения (`test_route_run_leaves_a_live_queue_on_all_three_sections`
  и `test_rerun_with_reset_replaces_previous_demo` проверяют именно прогон по
  маршруту и идемпотентность повторного прогона).
- **Кеш/шаблон БД** — это уже изменение смысла теста (проверяется настоящий
  путь сидера), поэтому не делалось.

## Почему BLOCKED

Ускорять нечего в тестовой зоне: 100% времени — продуктовый код сидера
(`app/seeds/**`), а ночному агенту правка продуктового кода запрещена.
Требуется решение человека: либо принять 204s как цену интеграционной
проверки, либо отдать тикет на оптимизацию `_run_route_progress` (batched
INSERT / меньше round-trip'ов) тому, кто имеет право менять `app/`.

## Что НЕ затронуто

Ни один файл не изменён; исследование выполнено чтением и одноразовыми
командами в отдельном worktree. Продуктовый код не правился.

## Откат

Не требуется (изменений нет).

## Артефакты

- `docs/night/logs/baseline-run1.log` — дамп `--durations=0`.
- `docs/night/logs/prof-rerun.prof` — профиль cProfile.
