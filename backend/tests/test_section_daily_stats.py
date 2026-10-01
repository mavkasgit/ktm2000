"""Регресс: ось дат дневной статистики участка (#259, развилка 1).

Окно и группировка обязаны жить в одной шкале — UTC:

* ``test_daily_stats_groups_by_utc_day_regardless_of_session_tz`` ловит
  зависимость группировки от TZ сессии БД: старая ``cast(created_at, Date)``
  считала день в поясе сессии и на не-UTC сервере уводила метку от окна.
* ``test_daily_stats_fallback_window_is_utc_day`` фиксирует форму
  fallback-окна «сегодня» (обе границы — aware UTC, один календарный день).
* ``test_daily_stats_treats_naive_client_input_as_utc`` фиксирует трактовку
  наивного входа клиента (фронт шлёт `YYYY-MM-DDTHH:MM:SS`) как UTC — aware
  значение при этом не переводится.
"""

from datetime import UTC, datetime, time, timedelta
from decimal import Decimal

import pytest
from app.api.routes import shopfloor as shopfloor_routes
from app.models.product import Product, ProductType
from app.models.section import Section
from app.models.user import User
from app.services.shopfloor.queries_sections import get_section_daily_stats
from app.stock.models import Reason, StockTransaction
from sqlalchemy import select, text


async def _seed_two_utc_days(session) -> int:
    """Продукт + участок + две проводки по обе стороны UTC-полуночи.

    Метки — 2026-06-01 23:30 UTC и 2026-06-02 00:30 UTC: разные UTC-сутки,
    но один локальный день в UTC+9 (08:30 и 09:30 второго числа). Поэтому
    тест кусается, если группировка пойдёт по TZ сессии БД, а не по UTC.
    """
    product = Product(sku="DST-UTC-1", name="Daily stats UTC", type=ProductType.finished_good)
    section = Section(code="DST-UTC-SEC", name="Daily stats section")
    session.add_all([product, section])
    await session.flush()

    system_user_id = await session.scalar(select(User.id).where(User.username == "system"))
    session.add_all(
        [
            StockTransaction(
                product_id=product.id,
                to_location_id=section.id,
                quantity=Decimal(1),
                reason=Reason.COMPLETE,
                created_at=datetime(2026, 6, 1, 23, 30, tzinfo=UTC),
                created_by=system_user_id,
            ),
            StockTransaction(
                product_id=product.id,
                to_location_id=section.id,
                quantity=Decimal(2),
                reason=Reason.COMPLETE,
                created_at=datetime(2026, 6, 2, 0, 30, tzinfo=UTC),
                created_by=system_user_id,
            ),
        ]
    )
    await session.commit()
    return section.id


@pytest.mark.asyncio
async def test_daily_stats_groups_by_utc_day_regardless_of_session_tz(session) -> None:
    section_id = await _seed_two_utc_days(session)

    # Сессия БД — не-UTC: в UTC+9 обе метки попадают в один локальный день
    # (2026-06-02). Группировка обязана остаться по UTC-дню.
    await session.execute(text("SET LOCAL TIME ZONE 'Asia/Tokyo'"))

    stats = await get_section_daily_stats(
        session,
        section_id=section_id,
        date_from=datetime(2026, 6, 1, tzinfo=UTC),
        date_to=datetime(2026, 6, 3, tzinfo=UTC),
    )
    by_date = {row["date"]: row for row in stats["daily_stats"]}

    assert set(by_date) == {"2026-06-01", "2026-06-02"}, (
        "день группировки уехал в TZ сессии БД вместо UTC"
    )
    assert by_date["2026-06-01"]["op_count"] == 1
    assert by_date["2026-06-02"]["op_count"] == 1
    assert Decimal(by_date["2026-06-01"]["good_quantity"]) == Decimal(1)
    assert Decimal(by_date["2026-06-02"]["good_quantity"]) == Decimal(2)


@pytest.mark.asyncio
async def test_daily_stats_fallback_window_is_utc_day(auth_client, monkeypatch) -> None:
    captured: dict[str, datetime] = {}

    async def _capture(_db, *, section_id, date_from, date_to):
        captured["date_from"] = date_from
        captured["date_to"] = date_to
        return {"section_id": section_id, "daily_stats": []}

    monkeypatch.setattr(shopfloor_routes, "get_section_daily_stats", _capture)

    before = datetime.now(UTC).date()
    response = await auth_client.get("/api/shopfloor/sections/1/daily-stats")
    assert response.status_code == 200

    d_from = captured["date_from"]
    d_to = captured["date_to"]
    assert d_from.tzinfo is UTC, "левая граница fallback-окна не в UTC"
    assert d_to.tzinfo is UTC, "правая граница fallback-окна не в UTC"
    assert d_from.date() in (before, datetime.now(UTC).date())
    assert d_from.date() == d_to.date(), "границы окна разъехались по календарным дням"
    assert d_from == datetime.combine(d_from.date(), time.min, tzinfo=UTC)
    assert d_to == datetime.combine(d_to.date(), time.max, tzinfo=UTC)
    # Сутки минус микросекунда: time.max = 23:59:59.999999.
    assert d_to - d_from == timedelta(days=1) - timedelta(microseconds=1)


@pytest.mark.asyncio
async def test_daily_stats_treats_naive_client_input_as_utc(auth_client, monkeypatch) -> None:
    captured: dict[str, datetime] = {}

    async def _capture(_db, *, section_id, date_from, date_to):
        captured["date_from"] = date_from
        captured["date_to"] = date_to
        return {"section_id": section_id, "daily_stats": []}

    monkeypatch.setattr(shopfloor_routes, "get_section_daily_stats", _capture)

    # Наивный вход (так его шлёт фронт) трактуется как UTC, а не как host-local.
    await auth_client.get(
        "/api/shopfloor/sections/1/daily-stats"
        "?date_from=2026-06-01T10:00:00&date_to=2026-06-01T18:00:00"
    )
    assert captured["date_from"] == datetime(2026, 6, 1, 10, 0, tzinfo=UTC)
    assert captured["date_to"] == datetime(2026, 6, 1, 18, 0, tzinfo=UTC)

    # Aware-вход уже несёт шкалу — не переводим (оффсет +05:00 сохраняется).
    await auth_client.get(
        "/api/shopfloor/sections/1/daily-stats"
        "?date_from=2026-06-01T10:00:00%2B05:00&date_to=2026-06-01T18:00:00%2B05:00"
    )
    assert captured["date_from"].utcoffset() == timedelta(hours=5)
    assert captured["date_from"].hour == 10
    assert captured["date_to"].utcoffset() == timedelta(hours=5)
