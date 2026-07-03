"""Tests for the storage-vs-production classification.

Covers:
- Pure classifier helpers (no DB)
- ``SectionOperation.operation_type`` is correctly persisted and read back
- ``RouteStage.stage_kind`` enforces transit-only-on-storage via CHECK constraint
- ``build_completed_stages_json`` drops transit stages, keeps production stages
- API: ``GET /api/sections/all/operations`` no longer fabricates SectionOperation
- API: ``GET /api/sections/storage-points`` returns only storage sections
- API: ``POST /api/routes/{id}/steps`` rejects storage section as production,
  accepts it as transit
"""
from __future__ import annotations

import pytest
import pytest_asyncio
from httpx import AsyncClient
from sqlalchemy import select, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.route import ProductionRoute, RouteStage, RouteOperation, SectionOperation
from app.models.section import Section
from app.services.route_storage_classifier import (
    STAGE_KIND_PRODUCTION,
    STAGE_KIND_TRANSIT,
    OPERATION_TYPE_PRODUCTION,
    OPERATION_TYPE_TRANSPORT,
    classify_section_role,
    classify_stages,
    infer_stage_kind,
    is_production_section,
    is_production_stage,
    is_storage_section,
    is_transit_stage,
    stage_display_name,
)
from app.services.shopfloor.common import build_completed_stages_json


# ---------- Pure classifier tests (no DB) ----------


def _make_section(code: str, type_: str) -> Section:
    return Section(code=code, name=code, type=type_, is_active=True, sort_order=0)


def test_is_storage_section():
    assert is_storage_section(_make_section("WH", "raw_stock")) is True
    assert is_storage_section(_make_section("WIP", "wip_stock")) is True
    assert is_storage_section(_make_section("FG", "finished_stock")) is True
    assert is_storage_section(_make_section("DRILL", "production")) is False
    assert is_storage_section(None) is False


def test_is_production_section():
    assert is_production_section(_make_section("DRILL", "production")) is True
    assert is_production_section(_make_section("WH", "raw_stock")) is False
    assert is_production_section(None) is False


def test_classify_section_role():
    assert classify_section_role(_make_section("DRILL", "production")) == "production"
    assert classify_section_role(_make_section("WH", "raw_stock")) == "storage"
    assert classify_section_role(_make_section("WIP", "wip_stock")) == "storage"
    assert classify_section_role(_make_section("FG", "finished_stock")) == "storage"


def test_infer_stage_kind():
    assert infer_stage_kind(section=_make_section("DRILL", "production")) == STAGE_KIND_PRODUCTION
    assert infer_stage_kind(section=_make_section("WH", "raw_stock")) == STAGE_KIND_TRANSIT
    assert infer_stage_kind(section=None, storage_section_id=42) == STAGE_KIND_TRANSIT
    assert infer_stage_kind(section=_make_section("DRILL", "production"), storage_section_id=None) == STAGE_KIND_PRODUCTION


def test_stage_display_name():
    drill = _make_section("DRILL", "production")
    wh = _make_section("WH", "raw_stock")
    fg = _make_section("FG", "finished_stock")

    prod_stage = RouteStage(sequence=1, section_id=drill.id, stage_kind="production")
    prod_stage.section = drill
    assert stage_display_name(prod_stage, None) == "DRILL"

    transit_stage = RouteStage(sequence=1, stage_kind="transit", storage_section_id=wh.id)
    assert "WH" in stage_display_name(transit_stage, wh)


# ---------- DB-backed tests ----------


async def _seed_basic_sections(session: AsyncSession) -> dict[str, Section]:
    """Create the default 11 sections and basic ops matching the production seeder."""
    data = [
        ("WH", "raw_stock"),
        ("DRILL", "production"),
        ("PRESS", "production"),
        ("SHOT", "production"),
        ("ANOD", "production"),
        ("WIP_WH", "wip_stock"),
        ("SAW", "production"),
        ("PACK", "production"),
        ("FG_WH", "finished_stock"),
        ("SHIPMENT", "finished_stock"),
        ("SENT", "finished_stock"),
    ]
    sections: dict[str, Section] = {}
    for code, type_ in data:
        s = Section(code=code, name=code, type=type_, is_active=True, sort_order=len(sections) * 10)
        session.add(s)
        sections[code] = s
    await session.flush()
    return sections


async def test_section_operation_operation_type_default_is_production(session: AsyncSession):
    sections = await _seed_basic_sections(session)
    op = SectionOperation(
        section_id=sections["DRILL"].id,
        operation_code="DRILL",
        operation_name="Drill",
        is_significant=True,
    )
    session.add(op)
    await session.flush()
    await session.refresh(op)
    assert op.operation_type == OPERATION_TYPE_PRODUCTION


async def test_section_operation_transport_only_on_storage(session: AsyncSession):
    sections = await _seed_basic_sections(session)
    op = SectionOperation(
        section_id=sections["DRILL"].id,  # production section
        operation_code="WEIRD",
        operation_name="Weird transport on production section",
        is_significant=False,
        operation_type=OPERATION_TYPE_TRANSPORT,
    )
    session.add(op)
    with pytest.raises(IntegrityError):
        await session.flush()
    await session.rollback()


async def test_section_operation_transport_allowed_on_storage(session: AsyncSession):
    sections = await _seed_basic_sections(session)
    op = SectionOperation(
        section_id=sections["WH"].id,
        operation_code="ISSUE_RAW",
        operation_name="Issue raw",
        is_significant=False,
        operation_type=OPERATION_TYPE_TRANSPORT,
    )
    session.add(op)
    await session.flush()
    await session.refresh(op)
    assert op.operation_type == OPERATION_TYPE_TRANSPORT


async def test_route_stage_transit_check_constraint(session: AsyncSession):
    """Transit stage pointing at a production section must be rejected by CHECK."""
    sections = await _seed_basic_sections(session)
    route = ProductionRoute(name="R-transit-bad", is_active=True)
    session.add(route)
    await session.flush()

    stage = RouteStage(
        route_id=route.id,
        sequence=1,
        section_id=sections["DRILL"].id,  # production, not storage
        stage_kind=STAGE_KIND_TRANSIT,
        storage_section_id=sections["DRILL"].id,
    )
    session.add(stage)
    with pytest.raises(IntegrityError):
        await session.flush()
    await session.rollback()


async def test_classify_stages_splits_production_and_transit(session: AsyncSession):
    sections = await _seed_basic_sections(session)
    route = ProductionRoute(name="R-classify", is_active=True)
    session.add(route)
    await session.flush()

    s1 = RouteStage(route_id=route.id, sequence=1, section_id=sections["DRILL"].id, stage_kind=STAGE_KIND_PRODUCTION)
    s2 = RouteStage(route_id=route.id, sequence=2, section_id=None, stage_kind=STAGE_KIND_TRANSIT, storage_section_id=sections["WIP_WH"].id)
    s3 = RouteStage(route_id=route.id, sequence=3, section_id=sections["ANOD"].id, stage_kind=STAGE_KIND_PRODUCTION)
    session.add_all([s1, s2, s3])
    await session.flush()

    session.add(RouteOperation(route_stage_id=s1.id, sequence=1, operation_code="DRILL", operation_name="Drill"))
    session.add(RouteOperation(route_stage_id=s3.id, sequence=1, operation_code="ANOD_01", operation_name="Silver"))
    await session.flush()

    production, transit = await classify_stages(session, [s1, s2, s3])
    assert {s.id for s in production} == {s1.id, s3.id}
    assert {s.id for s in transit} == {s2.id}
    assert is_transit_stage(s2) is True
    assert is_production_stage(s2) is False
    assert is_production_stage(s1) is True


async def test_build_completed_stages_json_drops_transit(session: AsyncSession):
    sections = await _seed_basic_sections(session)
    route = ProductionRoute(name="R-completed", is_active=True)
    session.add(route)
    await session.flush()

    s_drill = RouteStage(route_id=route.id, sequence=1, section_id=sections["DRILL"].id, stage_kind=STAGE_KIND_PRODUCTION)
    s_wip = RouteStage(route_id=route.id, sequence=2, section_id=None, stage_kind=STAGE_KIND_TRANSIT, storage_section_id=sections["WIP_WH"].id)
    s_anod = RouteStage(route_id=route.id, sequence=3, section_id=sections["ANOD"].id, stage_kind=STAGE_KIND_PRODUCTION)
    session.add_all([s_drill, s_wip, s_anod])
    await session.flush()
    session.add_all([
        RouteOperation(route_stage_id=s_drill.id, sequence=1, operation_code="DRILL", operation_name="Drill"),
        RouteOperation(route_stage_id=s_anod.id, sequence=1, operation_code="ANOD_01", operation_name="Silver"),
    ])
    await session.flush()

    completed = await build_completed_stages_json(session, [s_drill, s_wip, s_anod])
    assert len(completed) == 2
    section_ids = {c["section_id"] for c in completed}
    assert section_ids == {sections["DRILL"].id, sections["ANOD"].id}
    # WIP_WH must not appear even though it's a real section id
    assert sections["WIP_WH"].id not in section_ids


async def test_build_completed_stages_json_empty(session: AsyncSession):
    assert await build_completed_stages_json(session, []) == []


# ---------- API tests ----------


async def test_sections_all_operations_no_synthetic_fallback(client: AsyncClient, session: AsyncSession):
    """When a production section has no operations, the API must return empty list,
    NOT a fabricated SectionOperation with is_significant=True (the old bug)."""
    sections = await _seed_basic_sections(session)
    # Make sure DRILL has no operations
    res = await client.get("/api/sections/all/operations")
    assert res.status_code == 200, res.text
    payload = res.json()
    by_code = {p["code"]: p for p in payload}

    drill = by_code.get("DRILL")
    assert drill is not None
    assert drill["type"] == "production"
    assert drill["role"] == "production"
    # If the section has no real operations, list is empty and the flag is False.
    if not drill["operations"]:
        assert drill["has_real_operations"] is False
    else:
        # If a previous test seeded operations, all returned ops must be the real ones
        for op in drill["operations"]:
            assert op["operation_code"] != "DRILL" or op["id"] != 0  # not the synthetic id=0 hack


async def test_sections_storage_points_returns_only_storage(client: AsyncClient, session: AsyncSession):
    await _seed_basic_sections(session)
    res = await client.get("/api/sections/storage-points")
    assert res.status_code == 200, res.text
    payload = res.json()
    codes = {p["code"] for p in payload}
    assert {"WH", "WIP_WH", "FG_WH", "SHIPMENT", "SENT"} <= codes
    for p in payload:
        assert p["type"] in {"raw_stock", "wip_stock", "finished_stock"}
    # Production sections must not appear
    assert "DRILL" not in codes
    assert "ANOD" not in codes


async def test_create_route_step_rejects_storage_as_production(client: AsyncClient, session: AsyncSession):
    sections = await _seed_basic_sections(session)
    route = ProductionRoute(name="R-reject", is_active=True)
    session.add(route)
    await session.flush()
    await session.commit()

    res = await client.post(
        f"/api/routes/{route.id}/steps",
        json={
            "sequence": 1,
            "section_id": sections["WH"].id,
            "operation_code": "ISSUE_RAW",
            "operation_name": "Issue raw",
            "stage_kind": "production",
        },
    )
    assert res.status_code == 400, res.text
    assert "storage section" in res.json()["detail"].lower()


async def test_create_route_step_accepts_transit_for_storage(client: AsyncClient, session: AsyncSession):
    sections = await _seed_basic_sections(session)
    route = ProductionRoute(name="R-transit-ok", is_active=True)
    session.add(route)
    await session.flush()
    await session.commit()

    res = await client.post(
        f"/api/routes/{route.id}/steps",
        json={
            "sequence": 1,
            "section_id": sections["WIP_WH"].id,
            "operation_code": "MOVE",
            "operation_name": "ignore",
            "stage_kind": "transit",
            "storage_section_id": sections["WIP_WH"].id,
        },
    )
    assert res.status_code == 201, res.text
    body = res.json()
    assert body["stage_kind"] == "transit"
    assert body["storage_section_id"] == sections["WIP_WH"].id
    assert body["section_id"] is None
    # transit stages should not have a real operation linked
    stage_id = body["id"]
    op_count = await session.scalar(
        select(text("COUNT(*)")).select_from(RouteOperation).where(RouteOperation.route_stage_id == stage_id)
    )
    assert op_count == 0


async def test_create_route_step_transit_cannot_be_final(client: AsyncClient, session: AsyncSession):
    sections = await _seed_basic_sections(session)
    route = ProductionRoute(name="R-transit-final", is_active=True)
    session.add(route)
    await session.flush()
    await session.commit()

    res = await client.post(
        f"/api/routes/{route.id}/steps",
        json={
            "sequence": 1,
            "section_id": sections["WIP_WH"].id,
            "operation_name": "ignore",
            "stage_kind": "transit",
            "storage_section_id": sections["WIP_WH"].id,
            "is_final": True,
        },
    )
    assert res.status_code == 400, res.text
    assert "final" in res.json()["detail"].lower()
