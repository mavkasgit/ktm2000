# T-0264 — доска участка: наивные `date_from`/`date_to` трактуются как UTC

Тикет: https://github.com/mavkasgit/ktm2000/issues/264
Ветка: `night/2026-10-01`, worktree `C:/Users/LogoPrint/VibeCoding/ktm2000-night`.

## Проблема

`section_board` (`backend/app/api/routes/shopfloor.py`) прокидывал клиентские
`date_from`/`date_to` в `get_section_board` без нормализации, а запрос сравнивает
их с `WorkTask.created_at` (timestamptz). Фронт шлёт наивные строки
(`frontend/src/features/sections/pages/SectionsTasksPage.tsx:290` —
`${dateFrom}T00:00:00`), а asyncpg кодирует наивный `datetime` в timestamptz через
`astimezone(utc)` (`asyncpg/pgproto/codecs/datetime.pyx:222`), где объект без зоны
Python читает как **локальное время процесса**. На машине с TZ UTC+3 окно доски
уезжало: 1 июня 23:59:59 (наивно) превращалось в 1 июня 20:59:59 UTC, и задача с
меткой 22:30Z выпадала из «своего» дня. Прод-контейнер живёт в `TZ=UTC`, поэтому
там дефект не виден.

Тот же класс уже правился в `section_daily_stats` (#259): ось продукта — UTC,
общий хелпер `_naive_as_utc` (`shopfloor.py:63`).

## Правка

`shopfloor.py`, `section_board`: вход нормализуется тем же `_naive_as_utc`, что и
daily-stats; `None` остаётся `None` (у доски нет fallback-окна дня, в отличие от
daily-stats — окном дня вход не подменяем).

Тест: `backend/tests/test_section_board_dates.py`
- `test_board_treats_naive_client_input_as_utc` — наивный вход → aware UTC,
  aware (`+05:00`) сохраняет оффсет, отсутствие входа → `None`;
- `test_board_window_boundaries_are_utc_instants_regardless_of_session_tz` —
  границы окна — UTC-мгновения под `SET LOCAL TIME ZONE 'Asia/Tokyo'`;
- `test_board_naive_window_selects_task_by_utc_created_at` — сквозной HTTP-прогон:
  наивное окно 1 июня берёт задачу с меткой `2026-06-01T22:30Z`, окно 2 июня — нет.

## Доказательство

До правки (normalization временно отключена), `-k section_board_dates`:
`2 failed, 1 passed` — в том числе `assert 0 == 1` в сквозном тесте (задача
выпала из окна) и `datetime(2026, 6, 1, 0, 0) == datetime(..., tzinfo=UTC) → False`.
После правки, `-k section_board_dates`: `3 passed in 10.85s`.

Границы проверки `ruff check backend/app/api/routes/shopfloor.py --select DTZ` →
`All checks passed!`.

Полный backend-прогон (после этой правки, под нагрузкой):
**1996 passed, 3 warnings in 541.87s** (`PYTEST_NUM_WORKERS=3`, launcher, своя
run-DB; лог `logs/pytest-c8fd5d2a6919.log`).

## Что НЕ трогали

- `performed_at`/`accounted_at` в payload'ах завершения: это запись в timestamptz,
  не сравнение окна; класс другой (тикет про окно доски) — отдельный разбор, если
  понадобится. В модуле больше нет мест, где клиентский `date_from`/`date_to`
  уходит в сравнение с timestamptz (`grep` по модулю: только board и daily-stats).
- Сервис `get_section_board` и его запрос — нормализация на границе маршрута.
- Фронт не менялся.

## Критерии готовности

- [x] наивный вход на доске трактуется как UTC явно (общий `_naive_as_utc`);
- [x] тест сторожит границы окна и независимость от TZ сессии БД;
- [x] `ruff check backend/app/api/routes/shopfloor.py --select DTZ` → 0;
- [x] полный backend-прогон зелёный.

## Откат

`git revert <sha>` — правка локальна (маршрут + новый тестовый файл), схемы и
контрактов не меняет.
