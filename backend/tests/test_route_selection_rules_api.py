"""API write-валидация selection rules / profiles (тикет #24).

Ключевое: cross-ref violations возвращают HTTP 422, валидные payload —
201. Правила и профили не сохраняются со ссылками на несуществующие
sections / templates.
"""

from __future__ import annotations

import pytest
from sqlalchemy import select

from app.models.route import RouteRuleProfile, RouteSelectionRule
from app.models.section import Section

from tests.test_routes_seed import DEFAULT_SECTIONS, _seed_default_sections


async def _seed_sections_and_profile(session) -> RouteRuleProfile:
    await _seed_default_sections(session)
    profile = RouteRuleProfile(
        code="test_profile",
        name="Тестовый профиль",
        is_active=True,
        priority=1000,
    )
    session.add(profile)
    await session.commit()
    await session.refresh(profile)
    return profile


@pytest.mark.asyncio
async def test_create_rule_with_unknown_section_id_returns_422(client, session) -> None:
    await _seed_sections_and_profile(session)

    response = await client.post(
        "/api/route-selection-rules",
        json={
            "code": "bad_section_rule",
            "name": "Правило с битым section",
            "priority": 100,
            "is_active": True,
            "conditions": [],
            "actions": [{"action": "require_section", "section_id": 999_999}],
        },
    )
    assert response.status_code == 422
    assert "unknown section" in response.json()["detail"]


@pytest.mark.asyncio
async def test_create_rule_with_unknown_section_code_returns_422(client, session) -> None:
    await _seed_sections_and_profile(session)

    response = await client.post(
        "/api/route-selection-rules",
        json={
            "code": "bad_section_code_rule",
            "name": "Правило с битым section_code",
            "priority": 100,
            "is_active": True,
            "conditions": [],
            "actions": [
                {
                    "action": "set_operation",
                    "section_code": "NO_SUCH_SECTION",
                    "group_code": "DRILL",
                    "operation_code": "DRILL_01",
                }
            ],
        },
    )
    assert response.status_code == 422
    assert "unknown section_code" in response.json()["detail"]


@pytest.mark.asyncio
async def test_create_rule_with_unknown_profile_id_returns_422(client, session) -> None:
    await _seed_sections_and_profile(session)
    drill = await session.scalar(select(Section).where(Section.code == "DRILLING"))

    response = await client.post(
        "/api/route-selection-rules",
        json={
            "code": "bad_profile_rule",
            "name": "Правило с битым профилем",
            "priority": 100,
            "is_active": True,
            "profile_id": 999_999,
            "conditions": [],
            "actions": [{"action": "require_section", "section_id": drill.id}],
        },
    )
    assert response.status_code == 422
    assert response.json()["detail"] == "Invalid profile_id"


@pytest.mark.asyncio
async def test_create_rule_valid_returns_201(client, session) -> None:
    profile = await _seed_sections_and_profile(session)
    drill = await session.scalar(select(Section).where(Section.code == "DRILLING"))
    anod = await session.scalar(select(Section).where(Section.code == "ANODIZING"))

    response = await client.post(
        "/api/route-selection-rules",
        json={
            "code": "valid_rule",
            "name": "Валидное правило",
            "profile_id": profile.id,
            "priority": 100,
            "is_active": True,
            "conditions": [
                {"source": "payload", "field_path": "operation", "operator": "contains", "value": "сверл"}
            ],
            "actions": [
                {"action": "require_section", "section_id": drill.id},
                {"action": "exclude_section", "section_id": anod.id},
            ],
        },
    )
    assert response.status_code == 201
    data = response.json()
    assert data["code"] == "valid_rule"
    assert data["profile_code"] == "test_profile"
    assert data["actions"][0]["section_code"] == "DRILLING"

    saved = await session.scalar(select(RouteSelectionRule).where(RouteSelectionRule.code == "valid_rule"))
    assert saved is not None
    assert saved.profile_id == profile.id


@pytest.mark.asyncio
async def test_create_profile_with_unknown_route_section_returns_422(client, session) -> None:
    await _seed_default_sections(session)

    response = await client.post(
        "/api/route-rule-profiles",
        json={
            "code": "bad_sections_profile",
            "name": "Профиль с битыми секциями",
            "priority": 100,
            "route_sections": ["RAW_STOCK", "NO_SUCH_SECTION"],
        },
    )
    assert response.status_code == 422
    assert "unknown sections" in response.json()["detail"]


@pytest.mark.asyncio
async def test_create_profile_with_unknown_template_id_returns_422(client, session) -> None:
    await _seed_default_sections(session)

    response = await client.post(
        "/api/route-rule-profiles",
        json={
            "code": "bad_template_profile",
            "name": "Профиль с битым шаблоном",
            "priority": 100,
            "import_template_id": 999_999,
            "route_sections": ["RAW_STOCK"],
        },
    )
    assert response.status_code == 422
    assert response.json()["detail"] == "Invalid import_template_id"


@pytest.mark.asyncio
async def test_create_profile_valid_returns_201(client, session) -> None:
    await _seed_default_sections(session)

    response = await client.post(
        "/api/route-rule-profiles",
        json={
            "code": "valid_profile",
            "name": "Валидный профиль",
            "priority": 100,
            "route_sections": ["RAW_STOCK", "DRILLING", "FINISHED_STOCK"],
        },
    )
    assert response.status_code == 201
    data = response.json()
    assert data["code"] == "valid_profile"
    assert data["route_sections"] == ["RAW_STOCK", "DRILLING", "FINISHED_STOCK"]
