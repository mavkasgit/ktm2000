"""Регресс: ось дат доски участка — UTC (#264).

``section_board`` прокидывал клиентские ``date_from``/``date_to`` в запрос по
``WorkTask.created_at`` (timestamptz) без нормализации. asyncpg кодирует
наивный ``datetime`` в timestamptz через ``astimezone(utc)``, а объект без
зоны Python читает как локальное время **процесса** — окно доски уезжало от
UTC на host-offset (прод-контейнер живёт в ``TZ=UTC``, dev-машины — нет).
Лечится тем же, что и daily-stats (#259): общий хелпер ``_naive_as_utc``.

* ``test_board_treats_naive_client_input_as_utc`` — контракт маршрута: наивный
  вход становится aware UTC, aware не переводится, отсутствие входа остаётся
  ``None`` (окном дня не подменяется).
* ``test_board_window_boundaries_are_utc_instants_regardless_of_session_tz`` —
  границы окна — UTC-мгновения, не зависящие от TZ сессии БД.
* ``test_board_naive_window_selects_task_by_utc_created_at`` — сквозной прогон
  маршрута по реальным данным: наивное окно отбирает задачу по её UTC-метке.
"""

from datetime import UTC, datetime, timedelta

import pytest
from app.api.routes import shopfloor as shopfloor_routes
from app.services.shopfloor.queries_sections import get_section_board
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from tests.test_section_board_operation_fallback import (
    _create_task_for_route,
    _setup_press_section_with_null_route_step,
)


@pytest.mark.asyncio
async def test_board_treats_naive_client_input_as_utc(auth_client, monkeypatch) -> None:
    captured: dict[str, datetime | None] = {}

    async def _capture(_db, *, section_id, date_from=None, date_to=None, **_kwargs):
        captured["date_from"] = date_from
        captured["date_to"] = date_to
        return {"section_id": section_id, "tasks": [], "total": 0, "limit": 50, "offset": 0}

    monkeypatch.setattr(shopfloor_routes, "get_section_board", _capture)

    # Наивный вход (так его шлёт фронт, `YYYY-MM-DDTHH:MM:SS`) читается как UTC,
    # а не как host-local: границы окна не сдвигаются.
    response = await auth_client.get(
        "/api/shopfloor/sections/1/board"
        "?date_from=2026-06-01T00:00:00&date_to=2026-06-01T23:59:59"
    )
    assert response.status_code == 200
    assert captured["date_from"] == datetime(2026, 6, 1, 0, 0, tzinfo=UTC)
    assert captured["date_to"] == datetime(2026, 6, 1, 23, 59, 59, tzinfo=UTC)
    assert captured["date_from"].utcoffset() == timedelta(0)
    assert captured["date_to"].utcoffset() == timedelta(0)

    # Aware-вход уже несёт шкалу — не переводим (оффсет +05:00 сохраняется).
    await auth_client.get(
        "/api/shopfloor/sections/1/board"
        "?date_from=2026-06-01T10:00:00%2B05:00&date_to=2026-06-01T18:00:00%2B05:00"
    )
    assert captured["date_from"].utcoffset() == timedelta(hours=5)
    assert captured["date_from"].hour == 10
    assert captured["date_to"].utcoffset() == timedelta(hours=5)

    # Входа нет — фильтра нет: окном текущего дня доска не подменяется
    # (в отличие от daily-stats, где fallback обязателен).
    await auth_client.get("/api/shopfloor/sections/1/board")
    assert captured["date_from"] is None
    assert captured["date_to"] is None


async def _seed_press_task_at(session: AsyncSession, created_at: datetime) -> tuple[int, int]:
    """Участок пресса + одна задача с заданной меткой ``created_at`` (UTC)."""
    _raw_section, press_section, route, raw_stage, press_stage = (
        await _setup_press_section_with_null_route_step(session)
    )
    _product, _pp, _raw_task, press_task = await _create_task_for_route(
        session, route, raw_stage, press_stage, {"operation_code": "PRESS_WINDOW"}
    )
    press_task.created_at = created_at
    await session.flush()
    return press_section.id, press_task.id


@pytest.mark.asyncio
async def test_board_window_boundaries_are_utc_instants_regardless_of_session_tz(
    session: AsyncSession,
) -> None:
    # 2026-06-01 22:30 UTC = 2026-06-02 07:30 в UTC+9: под TZ сессии Asia/Tokyo
    # эта метка той же даты, что и следующий UTC-день, — окно обязано решаться
    # UTC-мгновениями, а не поясом сессии.
    section_id, task_id = await _seed_press_task_at(session, datetime(2026, 6, 1, 22, 30, tzinfo=UTC))
    await session.execute(text("SET LOCAL TIME ZONE 'Asia/Tokyo'"))

    in_window = await get_section_board(
        session,
        section_id=section_id,
        date_from=datetime(2026, 6, 1, 0, 0, tzinfo=UTC),
        date_to=datetime(2026, 6, 1, 23, 59, 59, tzinfo=UTC),
    )
    assert [task["id"] for task in in_window["tasks"]] == [task_id], (
        "границы окна доски уехали в TZ сессии БД вместо UTC"
    )

    next_day = await get_section_board(
        session,
        section_id=section_id,
        date_from=datetime(2026, 6, 2, 0, 0, tzinfo=UTC),
        date_to=datetime(2026, 6, 2, 23, 59, 59, tzinfo=UTC),
    )
    assert next_day["tasks"] == [], "метка 2026-06-01T22:30Z попала в окно 2 июня"


@pytest.mark.asyncio
async def test_board_naive_window_selects_task_by_utc_created_at(
    auth_client, session: AsyncSession
) -> None:
    """Сквозной маршрут: наивное окно 1 июня берёт задачу с меткой 22:30 UTC."""
    section_id, task_id = await _seed_press_task_at(session, datetime(2026, 6, 1, 22, 30, tzinfo=UTC))

    response = await auth_client.get(
        f"/api/shopfloor/sections/{section_id}/board"
        "?date_from=2026-06-01T00:00:00&date_to=2026-06-01T23:59:59"
    )
    assert response.status_code == 200
    body = response.json()
    assert body["total"] == 1
    assert [task["id"] for task in body["tasks"]] == [task_id]

    next_day = await auth_client.get(
        f"/api/shopfloor/sections/{section_id}/board"
        "?date_from=2026-06-02T00:00:00&date_to=2026-06-02T23:59:59"
    )
    assert next_day.json()["total"] == 0
