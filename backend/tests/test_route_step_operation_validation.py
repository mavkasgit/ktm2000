"""Tests for route step operation_code validation.

Ensures that route_steps cannot be created with an operation_code
that is not registered in section_operations for the target section.
"""

import pytest

from app.models.route import ProductionRoute, RouteStage, RouteOperation, SectionOperation
from app.models.section import Section


@pytest.mark.asyncio
async def test_create_step_with_valid_operation_code(client, session) -> None:
    """Creating a route step with a registered operation_code should succeed."""
    section = Section(code="SEC-OP-VALID", name="Section Op Valid", is_active=True)
    session.add(section)
    await session.commit()

    # Register operation
    session.add(SectionOperation(section_id=section.id, operation_code="TEST_OP", operation_name="Test Op"))
    await session.commit()

    route = await client.post("/api/routes", json={"name": "Route Op Valid", "is_active": True})
    assert route.status_code == 201
    route_id = route.json()["id"]

    step = await client.post(
        f"/api/routes/{route_id}/steps",
        json={
            "sequence": 1,
            "section_id": section.id,
            "operation_code": "TEST_OP",
            "operation_name": "Test Op",
            "is_final": True,
        },
    )
    assert step.status_code == 201
    assert step.json()["operation_code"] == "TEST_OP"


@pytest.mark.asyncio
async def test_create_step_with_unregistered_operation_code(client, session) -> None:
    """Creating a route step with an unregistered operation_code should fail."""
    section = Section(code="SEC-OP-INVALID", name="Section Op Invalid", is_active=True)
    session.add(section)
    await session.commit()

    # Register only one operation
    session.add(SectionOperation(section_id=section.id, operation_code="VALID_OP", operation_name="Valid Op"))
    await session.commit()

    route = await client.post("/api/routes", json={"name": "Route Op Invalid", "is_active": True})
    assert route.status_code == 201
    route_id = route.json()["id"]

    # Try to create step with unregistered operation_code
    step = await client.post(
        f"/api/routes/{route_id}/steps",
        json={
            "sequence": 1,
            "section_id": section.id,
            "operation_code": "NONEXISTENT_OP",
            "operation_name": "Nonexistent Op",
            "is_final": True,
        },
    )
    assert step.status_code == 400
    assert "not registered" in step.json()["detail"].lower()


@pytest.mark.asyncio
async def test_replace_steps_with_unregistered_operation_code(client, session) -> None:
    """Replacing all route steps with an unregistered operation_code should fail."""
    section = Section(code="SEC-OP-REPLACE", name="Section Op Replace", is_active=True)
    session.add(section)
    await session.commit()

    session.add(SectionOperation(section_id=section.id, operation_code="VALID_OP", operation_name="Valid Op"))
    await session.commit()

    route = await client.post("/api/routes", json={"name": "Route Op Replace", "is_active": True})
    assert route.status_code == 201
    route_id = route.json()["id"]

    # Replace with invalid operation_code
    result = await client.put(
        f"/api/routes/{route_id}/steps",
        json=[
            {
                "sequence": 1,
                "section_id": section.id,
                "operation_code": "BAD_OP",
                "operation_name": "Bad Op",
                "is_final": True,
            }
        ],
    )
    assert result.status_code == 400
    assert "not registered" in result.json()["detail"].lower()


@pytest.mark.asyncio
async def test_replace_steps_with_mixed_valid_and_invalid_operation_codes(client, session) -> None:
    """Replacing steps where one step is valid and another is invalid should fail on the invalid one."""
    section1 = Section(code="SEC-MIXED-1", name="Section Mixed 1", is_active=True)
    section2 = Section(code="SEC-MIXED-2", name="Section Mixed 2", is_active=True)
    session.add_all([section1, section2])
    await session.commit()

    # Only section1 has VALID_OP registered
    session.add(SectionOperation(section_id=section1.id, operation_code="VALID_OP", operation_name="Valid Op"))
    await session.commit()

    route = await client.post("/api/routes", json={"name": "Route Mixed", "is_active": True})
    assert route.status_code == 201
    route_id = route.json()["id"]

    # First step valid, second step invalid (section2 has no operations registered)
    result = await client.put(
        f"/api/routes/{route_id}/steps",
        json=[
            {
                "sequence": 1,
                "section_id": section1.id,
                "operation_code": "VALID_OP",
                "operation_name": "Valid Op",
                "is_final": False,
            },
            {
                "sequence": 2,
                "section_id": section2.id,
                "operation_code": "MISSING_OP",
                "operation_name": "Missing Op",
                "is_final": True,
            }
        ],
    )
    assert result.status_code == 400
    assert "not registered" in result.json()["detail"].lower()


@pytest.mark.asyncio
async def test_press_section_rejects_press_operation_code(client, session) -> None:
    """Press section (like real DB) should reject 'PRESS' since only PRESS_WINDOW and PRESS_COMB are registered."""
    press_section = Section(code="PRESS", name="Пресс", is_active=True)
    session.add(press_section)
    await session.commit()

    # Register only the two real operations
    session.add_all([
        SectionOperation(section_id=press_section.id, operation_code="PRESS_WINDOW", operation_name="Пресс (окно)", is_significant=True),
        SectionOperation(section_id=press_section.id, operation_code="PRESS_COMB", operation_name="Пресс (гребенка)", is_significant=True),
    ])
    await session.commit()

    route = await client.post("/api/routes", json={"name": "ГП Пресс", "is_active": True})
    assert route.status_code == 201
    route_id = route.json()["id"]

    # Trying to add 'PRESS' should fail
    step = await client.post(
        f"/api/routes/{route_id}/steps",
        json={
            "sequence": 1,
            "section_id": press_section.id,
            "operation_code": "PRESS",
            "operation_name": "Пресс",
            "is_final": True,
        },
    )
    assert step.status_code == 400
    assert "not registered" in step.json()["detail"].lower()

    # But PRESS_WINDOW should work
    step2 = await client.post(
        f"/api/routes/{route_id}/steps",
        json={
            "sequence": 1,
            "section_id": press_section.id,
            "operation_code": "PRESS_WINDOW",
            "operation_name": "Пресс (окно)",
            "is_final": True,
        },
    )
    assert step2.status_code == 201


@pytest.mark.asyncio
async def test_create_step_with_null_operation_code_is_allowed(client, session) -> None:
    """NULL operation_code is allowed — operation comes from source_payload."""
    press_section = Section(code="PRESS-NULL", name="Пресс NULL", is_active=True)
    session.add(press_section)
    await session.commit()

    session.add_all([
        SectionOperation(section_id=press_section.id, operation_code="PRESS_WINDOW", operation_name="Пресс (окно)", is_significant=True),
        SectionOperation(section_id=press_section.id, operation_code="PRESS_COMB", operation_name="Пресс (гребенка)", is_significant=True),
    ])
    await session.commit()

    route = await client.post("/api/routes", json={"name": "ГП Пресс NULL", "is_active": True})
    assert route.status_code == 201
    route_id = route.json()["id"]

    # NULL operation_code should succeed
    step = await client.post(
        f"/api/routes/{route_id}/steps",
        json={
            "sequence": 1,
            "section_id": press_section.id,
            "operation_code": None,
            "operation_name": "Пресс",
            "is_final": True,
        },
    )
    assert step.status_code == 201
    assert step.json()["operation_code"] is None
