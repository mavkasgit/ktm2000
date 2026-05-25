"""Tests for section operations icon/icon_color CRUD."""
import pytest
from sqlalchemy import select

from app.models.route import SectionOperation
from app.models.section import Section


async def _make_section(session, code: str = "TEST-DRILL", name: str = "Drill Test") -> Section:
    section = Section(code=code, name=name, kind="production")
    session.add(section)
    await session.flush()
    return section


@pytest.mark.asyncio
async def test_create_section_operation_with_icon_and_color(client, session) -> None:
    """Creating an operation with icon and icon_color should persist both fields."""
    section = await _make_section(session, "ICON-TEST-1", "Icon Test 1")

    response = await client.post(
        f"/api/shopfloor/sections/{section.id}/operations",
        json={
            "operation_code": "DRILL_ICON",
            "operation_name": "Drill with icon",
            "is_significant": True,
            "icon": "Drill",
            "icon_color": "#3B82F6",
        },
    )
    assert response.status_code == 200
    data = response.json()
    assert data["icon"] == "Drill"
    assert data["icon_color"] == "#3B82F6"
    assert data["is_significant"] is True

    # Verify in DB
    op = await session.scalar(
        select(SectionOperation).where(SectionOperation.operation_code == "DRILL_ICON")
    )
    assert op is not None
    assert op.icon == "Drill"
    assert op.icon_color == "#3B82F6"


@pytest.mark.asyncio
async def test_create_section_operation_without_icon_defaults_to_null(client, session) -> None:
    """Creating an operation without icon/icon_color should store null."""
    section = await _make_section(session, "ICON-TEST-2", "Icon Test 2")

    response = await client.post(
        f"/api/shopfloor/sections/{section.id}/operations",
        json={
            "operation_code": "DRILL_NO_ICON",
            "operation_name": "Drill without icon",
            "is_significant": False,
        },
    )
    assert response.status_code == 200
    data = response.json()
    assert data["icon"] is None
    assert data["icon_color"] is None


@pytest.mark.asyncio
async def test_update_section_operation_icon_and_color(client, session) -> None:
    """Updating icon and icon_color should persist the new values."""
    section = await _make_section(session, "ICON-TEST-3", "Icon Test 3")

    # Create without icon
    create_resp = await client.post(
        f"/api/shopfloor/sections/{section.id}/operations",
        json={
            "operation_code": "UPDATE_ICON",
            "operation_name": "Update icon test",
            "is_significant": False,
        },
    )
    assert create_resp.status_code == 200
    op_id = create_resp.json()["id"]

    # Update icon and color
    update_resp = await client.patch(
        f"/api/shopfloor/sections/{section.id}/operations/{op_id}",
        json={
            "icon": "Factory",
            "icon_color": "#10B981",
        },
    )
    assert update_resp.status_code == 200
    data = update_resp.json()
    assert data["icon"] == "Factory"
    assert data["icon_color"] == "#10B981"

    # Verify in DB
    op = await session.get(SectionOperation, op_id)
    assert op is not None
    assert op.icon == "Factory"
    assert op.icon_color == "#10B981"


@pytest.mark.asyncio
async def test_get_section_operations_returns_icon_fields(client, session) -> None:
    """GET operations endpoint should return icon and icon_color fields."""
    section = await _make_section(session, "ICON-TEST-4", "Icon Test 4")

    # Create operations with and without icons
    await client.post(
        f"/api/shopfloor/sections/{section.id}/operations",
        json={
            "operation_code": "OP_WITH",
            "operation_name": "With icon",
            "icon": "Sparkles",
            "icon_color": "#F59E0B",
        },
    )
    await client.post(
        f"/api/shopfloor/sections/{section.id}/operations",
        json={
            "operation_code": "OP_WITHOUT",
            "operation_name": "Without icon",
        },
    )

    response = await client.get(f"/api/shopfloor/sections/{section.id}/operations")
    assert response.status_code == 200
    ops = response.json()
    assert len(ops) == 2

    op_with = next(o for o in ops if o["operation_code"] == "OP_WITH")
    assert op_with["icon"] == "Sparkles"
    assert op_with["icon_color"] == "#F59E0B"

    op_without = next(o for o in ops if o["operation_code"] == "OP_WITHOUT")
    assert op_without["icon"] is None
    assert op_without["icon_color"] is None


@pytest.mark.asyncio
async def test_create_section_operation_explicit_null_icon(client, session) -> None:
    """Creating with explicit null icon should store null."""
    section = await _make_section(session, "ICON-TEST-5", "Icon Test 5")

    response = await client.post(
        f"/api/shopfloor/sections/{section.id}/operations",
        json={
            "operation_code": "NULL_ICON",
            "operation_name": "Null icon test",
            "icon": None,
            "icon_color": None,
        },
    )
    assert response.status_code == 200
    data = response.json()
    assert data["icon"] is None
    assert data["icon_color"] is None


@pytest.mark.asyncio
async def test_update_section_operation_remove_icon(client, session) -> None:
    """Updating icon to null should remove it."""
    section = await _make_section(session, "ICON-TEST-6", "Icon Test 6")

    # Create with icon
    create_resp = await client.post(
        f"/api/shopfloor/sections/{section.id}/operations",
        json={
            "operation_code": "REMOVE_ICON",
            "operation_name": "Remove icon test",
            "icon": "Building",
            "icon_color": "#EF4444",
        },
    )
    assert create_resp.status_code == 200
    op_id = create_resp.json()["id"]

    # Remove icon
    update_resp = await client.patch(
        f"/api/shopfloor/sections/{section.id}/operations/{op_id}",
        json={
            "icon": None,
            "icon_color": None,
        },
    )
    assert update_resp.status_code == 200
    data = update_resp.json()
    assert data["icon"] is None
    assert data["icon_color"] is None
