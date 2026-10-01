"""Tests for the employees module (HRMS sync, preview, list)."""
from datetime import UTC, datetime
from unittest.mock import AsyncMock, patch

import pytest
from app.models.hrms_employee import HrmsEmployee
from app.services.hrms_employees import (
    _SORT_COLUMNS,
    _SORT_DEFAULT,
    _SORT_NULLS_LAST_FIELDS,
    VALID_SORT_FIELDS,
    HrmsSyncError,
    _build_employees_from_items,
    list_employees,
    preview_sync,
    sync_employees,
)
from sqlalchemy import func, select, text

# ─── Unit: _build_employees_from_items ───────────────────────────────


def test_build_employees_skips_invalid() -> None:
    raw = [
        {"id": 1, "name": "Alice", "tab_number": "A1"},
        {"id": None, "name": "NoId"},
        {"name": "NoIdEither"},
        {"id": 2, "name": ""},
        {"id": 3, "name": "Bob"},
    ]
    synced_at = datetime(2026, 7, 28, 12, 0, tzinfo=UTC)
    employees = _build_employees_from_items(raw, synced_at)
    assert len(employees) == 2
    assert employees[0].hrms_id == 1
    assert employees[1].hrms_id == 3


def test_build_employees_normalizes_fields() -> None:
    raw = [
        {
            "id": 10,
            "name": "Иванов",
            "tab_number": 488,
            "position": {"id": 1, "name": "Оператор"},
            "department": {"id": 2, "name": "Цех АСУ"},
        },
    ]
    synced_at = datetime(2026, 7, 28, tzinfo=UTC)
    employees = _build_employees_from_items(raw, synced_at)
    assert len(employees) == 1
    emp = employees[0]
    assert emp.tab_number == "488"
    assert emp.position == "Оператор"
    assert emp.department == "Цех АСУ"


# ─── Integration: sync_employees ─────────────────────────────────────


@pytest.mark.asyncio
async def test_sync_employees_replaces_cache(session) -> None:
    session.add(HrmsEmployee(hrms_id=99, name="Old", synced_at=datetime(2020, 1, 1, tzinfo=UTC)))
    await session.commit()

    hrms_items = [{"id": 1, "name": "New Employee"}]
    with patch("app.services.hrms_employees.fetch_employees_from_hrms", new=AsyncMock(return_value=hrms_items)):
        employees, _synced_at = await sync_employees(session)

    assert len(employees) == 1
    assert employees[0].hrms_id == 1
    assert employees[0].name == "New Employee"

    rows = list((await session.execute(select(HrmsEmployee))).scalars().all())
    assert len(rows) == 1
    assert rows[0].hrms_id == 1


@pytest.mark.asyncio
async def test_sync_employees_empty_raises(session) -> None:
    with (
        patch("app.services.hrms_employees.fetch_employees_from_hrms", new=AsyncMock(return_value=[])),
        pytest.raises(HrmsSyncError, match="пустой список"),
    ):
        await sync_employees(session)


@pytest.mark.asyncio
async def test_sync_employees_all_invalid_raises(session) -> None:
    with (
        patch("app.services.hrms_employees.fetch_employees_from_hrms", new=AsyncMock(return_value=[{"name": "NoId"}])),
        pytest.raises(HrmsSyncError, match="без валидных"),
    ):
        await sync_employees(session)


# ─── Integration: preview_sync ───────────────────────────────────────


@pytest.mark.asyncio
async def test_preview_sync_diff(session) -> None:
    synced_at = datetime(2026, 7, 1, tzinfo=UTC)
    session.add(HrmsEmployee(hrms_id=1, name="Alice", synced_at=synced_at))
    session.add(HrmsEmployee(hrms_id=2, name="Bob", synced_at=synced_at))
    await session.commit()

    hrms_items = [
        {"id": 1, "name": "Alice Updated"},
        {"id": 3, "name": "Charlie"},
    ]
    with patch("app.services.hrms_employees.fetch_employees_from_hrms", new=AsyncMock(return_value=hrms_items)):
        preview = await preview_sync(session)

    assert len(preview.diff.added) == 1
    assert preview.diff.added[0].id == 3
    assert len(preview.diff.removed) == 1
    assert preview.diff.removed[0].id == 2
    assert len(preview.diff.changed) == 1
    assert preview.diff.changed[0].before.name == "Alice"
    assert preview.diff.changed[0].after.name == "Alice Updated"
    assert "name" in preview.diff.changed[0].fields
    assert preview.diff.unchanged_count == 0

    # DB unchanged
    count = await session.scalar(select(func.count()).select_from(HrmsEmployee))
    assert count == 2


@pytest.mark.asyncio
async def test_preview_sync_does_not_modify_db(session) -> None:
    session.add(HrmsEmployee(hrms_id=10, name="Persistent", synced_at=datetime(2026, 7, 1, tzinfo=UTC)))
    await session.commit()

    hrms_items = [{"id": 10, "name": "Changed"}]
    with patch("app.services.hrms_employees.fetch_employees_from_hrms", new=AsyncMock(return_value=hrms_items)):
        await preview_sync(session)

    rows = list((await session.execute(select(HrmsEmployee))).scalars().all())
    assert len(rows) == 1
    assert rows[0].name == "Persistent"


# ─── Integration: list_employees ─────────────────────────────────────


@pytest.mark.asyncio
async def test_list_employees_empty(session) -> None:
    employees, total, synced_at = await list_employees(session)
    assert employees == []
    assert total == 0
    assert synced_at is None


@pytest.mark.asyncio
async def test_list_employees_with_data(session) -> None:
    synced_at = datetime(2026, 7, 28, tzinfo=UTC)
    session.add(HrmsEmployee(hrms_id=1, name="Alice", department="Цех А", synced_at=synced_at))
    session.add(HrmsEmployee(hrms_id=2, name="Bob", department="Цех Б", synced_at=synced_at))
    await session.commit()

    employees, total, _ = await list_employees(session)
    assert total == 2
    assert employees[0].name == "Alice"  # sorted by name asc


@pytest.mark.asyncio
async def test_list_employees_search(session) -> None:
    synced_at = datetime(2026, 7, 28, tzinfo=UTC)
    session.add(HrmsEmployee(hrms_id=1, name="Иванов Иван", synced_at=synced_at))
    session.add(HrmsEmployee(hrms_id=2, name="Петров Пётр", synced_at=synced_at))
    await session.commit()

    employees, total, _ = await list_employees(session, search="Иванов")
    assert total == 1
    assert employees[0].hrms_id == 1


@pytest.mark.asyncio
async def test_list_employees_department_filter(session) -> None:
    synced_at = datetime(2026, 7, 28, tzinfo=UTC)
    session.add(HrmsEmployee(hrms_id=1, name="A", department="Цех АСУ", synced_at=synced_at))
    session.add(HrmsEmployee(hrms_id=2, name="B", department="Цех Мех", synced_at=synced_at))
    await session.commit()

    employees, total, _ = await list_employees(session, department="АСУ")
    assert total == 1
    assert employees[0].hrms_id == 1


# ─── Integration: сортировка по ?sort=field:order,... ─────────────────


@pytest.mark.asyncio
async def test_list_employees_sort_two_priorities(session) -> None:
    """Второй приоритет решает порядок внутри групп с одинаковым первым полем.

    Данные засеяны так, что по ``department`` пары идут одинаковыми группами
    и различается только второй ключ. Ни сортировка по одной колонке, ни
    последовательные ``order_by`` такого порядка не дают.
    """
    synced_at = datetime(2026, 7, 28, tzinfo=UTC)
    for hrms_id, name, tab_number, department in [
        (1, "Alpha", "T-001", "Цех А"),
        (2, "Bravo", "T-002", "Цех А"),
        (3, "Charlie", "T-003", "Цех Б"),
        (4, "Delta", "T-004", "Цех Б"),
    ]:
        session.add(HrmsEmployee(
            hrms_id=hrms_id, name=name, tab_number=tab_number,
            department=department, synced_at=synced_at,
        ))
    await session.commit()

    employees, total, _ = await list_employees(session, sort="department:asc,tab_number:desc")
    assert total == 4
    assert [e.name for e in employees] == ["Bravo", "Alpha", "Delta", "Charlie"]


@pytest.mark.asyncio
async def test_list_employees_sort_tiebreaker_breaks_equal_values(session) -> None:
    """Равные значения сортировки разложены по hrms_id: порядок детерминирован.

    Все ``name`` одинаковы, поэтому решает только tiebreaker. UPDATE части строк
    переписывает их в хвост таблицы: физический порядок хранения перестаёт
    совпадать с порядком hrms_id, и сортировка без tiebreaker отдаёт его вместо
    возрастающего — именно это ломало переход между страницами.
    """
    synced_at = datetime(2026, 7, 28, tzinfo=UTC)
    for index in range(6):
        session.add(HrmsEmployee(
            hrms_id=index + 1, name="Same Name", tab_number=f"T-{index:03d}", synced_at=synced_at,
        ))
    await session.commit()
    await session.execute(
        text("UPDATE hrms_employees SET name = 'Same Name' WHERE hrms_id IN (3,4,5)")
    )
    await session.commit()

    employees, total, _ = await list_employees(session, sort="name:asc")
    assert total == 6
    assert [e.hrms_id for e in employees] == [1, 2, 3, 4, 5, 6]

    page, _, _ = await list_employees(session, sort="name:asc", limit=2, offset=2)
    assert [e.hrms_id for e in page] == [3, 4]


@pytest.mark.asyncio
async def test_list_employees_sort_nulls_last_in_both_directions(session) -> None:
    """Пустая должность уходит в конец и при asc, и при desc.

    В Postgres DESC по умолчанию ставит NULL первым: оператор кликнул
    «спустить», а сотрудники без должности оказывались наверху списка.
    """
    synced_at = datetime(2026, 7, 28, tzinfo=UTC)
    for index, position in [(1, "Инженер"), (2, "Мастер"), (3, None), (4, None)]:
        session.add(HrmsEmployee(
            hrms_id=index, name=f"Emp {index}", position=position, synced_at=synced_at,
        ))
    await session.commit()

    for order in ("asc", "desc"):
        employees, total, _ = await list_employees(session, sort=f"position:{order}")
        assert total == 4, order
        assert {e.hrms_id for e in employees[-2:]} == {3, 4}, order
        assert {e.hrms_id for e in employees[:2]} == {1, 2}, order


@pytest.mark.asyncio
async def test_list_employees_sort_invalid_field_and_order_400(session) -> None:
    """Молчаливый фолбэк запрещён: поле вне таблицы — 400, не sort по name."""
    from fastapi import HTTPException

    with pytest.raises(HTTPException) as unknown_field:
        await list_employees(session, sort="synced_at:asc")
    assert unknown_field.value.status_code == 400

    with pytest.raises(HTTPException) as unknown_order:
        await list_employees(session, sort="name:sideways")
    assert unknown_order.value.status_code == 400


@pytest.mark.asyncio
async def test_get_employees_endpoint_sort_contract(auth_client) -> None:
    """HTTP-контракт: 2+ приоритета принимаются, плохое поле/направление — 400.

    Сепаратные sort_by/sort_order больше не принимаются: лишние query-параметры
    FastAPI игнорирует, поэтому проверяем, что они не влияют на порядок строк.
    """
    ok = await auth_client.get("/api/employees?sort=department:asc,name:desc&limit=50")
    assert ok.status_code == 200, ok.text

    bad_field = await auth_client.get("/api/employees?sort=synced_at:asc")
    assert bad_field.status_code == 400

    bad_order = await auth_client.get("/api/employees?sort=name:sideways")
    assert bad_order.status_code == 400

    legacy = await auth_client.get("/api/employees?sort_by=name&sort_order=desc")
    assert legacy.status_code == 200
    legacy_body = await auth_client.get("/api/employees?limit=50")
    assert legacy.json()["employees"] == legacy_body.json()["employees"]


def test_employees_sort_table_keys_match_valid_fields() -> None:
    """Таблица резолва и набор допустимых полей не разъезжаются.

    Ловит дрейф: поле, добавленное в одну сторону и забытое в другой, дало бы
    либо 400 на существующей колонке, либо поле в контракте без резолва.
    """
    assert set(_SORT_COLUMNS) == VALID_SORT_FIELDS
    assert {"hrms_id", "name", "tab_number", "position", "department"} == VALID_SORT_FIELDS
    assert set(_SORT_NULLS_LAST_FIELDS) <= VALID_SORT_FIELDS
    assert _SORT_DEFAULT.field in VALID_SORT_FIELDS


# ─── HTTP endpoint tests ─────────────────────────────────────────────


@pytest.mark.asyncio
async def test_get_employees_endpoint(auth_client) -> None:
    response = await auth_client.get("/api/employees")
    assert response.status_code == 200
    data = response.json()
    assert "employees" in data
    assert "total" in data
    assert "synced_at" in data


@pytest.mark.asyncio
async def test_sync_endpoint_502_when_hrms_unavailable(auth_client) -> None:
    with patch(
        "app.services.hrms_employees.fetch_employees_from_hrms",
        new=AsyncMock(side_effect=HrmsSyncError("HRMS недоступен")),
    ):
        response = await auth_client.post("/api/employees/sync")
    assert response.status_code == 502
    assert "hrms" in response.json()["detail"].lower()


@pytest.mark.asyncio
async def test_sync_endpoint_success(auth_client, session) -> None:
    hrms_items = [{"id": 1, "name": "Тестовый сотрудник", "tab_number": "T1"}]
    with patch("app.services.hrms_employees.fetch_employees_from_hrms", new=AsyncMock(return_value=hrms_items)):
        response = await auth_client.post("/api/employees/sync")
    assert response.status_code == 200
    data = response.json()
    assert data["total"] == 1
    assert data["employees"][0]["name"] == "Тестовый сотрудник"


@pytest.mark.asyncio
async def test_preview_endpoint_success(auth_client, session) -> None:
    hrms_items = [{"id": 1, "name": "Alice"}]
    with patch("app.services.hrms_employees.fetch_employees_from_hrms", new=AsyncMock(return_value=hrms_items)):
        response = await auth_client.post("/api/employees/sync/preview")
    assert response.status_code == 200
    data = response.json()
    assert "diff" in data
    assert "added" in data["diff"]
    assert len(data["diff"]["added"]) == 1
