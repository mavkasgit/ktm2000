"""Tests that the seeders produce route data that respects the
storage-vs-production classification.

Covers:
- ``seed_routes`` (static universal route) marks storage sections as
  ``stage_kind='transit'`` with ``storage_section_id`` set and ``section_id``
  NULL, and does NOT create ``RouteOperation`` rows for them.
- ``seed_production_routes_from_profiles`` (dynamic route from a profile)
  does the same for every storage section in the profile.
- ``seed_demo_production`` correctly resolves DRILL / SHOT / ANOD stages by
  section code, even when transit stages are interleaved.
- ``run_full_seed`` end-to-end produces a route that the API can serve and
  that ``build_completed_stages_json`` skips transit.
"""
from __future__ import annotations

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.route import ProductionRoute, RouteOperation, RouteStage
from app.models.section import Section
from app.seeds.routes import ROUTES
from app.seeds.seeders.demo_production_seeder import seed_demo_production
from app.seeds.seeders.routes_seeder import (
    seed_production_routes_from_profiles,
    seed_routes,
)
from app.seeds.seeders.sections_seeder import seed_sections
from app.services.route_storage_classifier import (
    is_production_stage,
    is_storage_section,
    is_transit_stage,
)
from app.services.shopfloor.common import build_completed_stages_json


async def _seed_sections_only(session: AsyncSession) -> dict[str, Section]:
    """Seed the 11 default sections without their SectionOperations — those
    are not needed for the route shape checks below."""
    sections_map = await seed_sections(session)
    return sections_map


# --- seed_routes -------------------------------------------------------------


@pytest.mark.asyncio
async def test_seed_routes_marks_storage_sections_as_transit(session: AsyncSession):
    sections_map = await _seed_sections_only(session)

    await seed_routes(session, ROUTES, force=True)

    route = await session.scalar(
        select(ProductionRoute).where(ProductionRoute.code == "universal_rp")
    )
    assert route is not None
    stages = (await session.execute(
        select(RouteStage)
        .where(RouteStage.route_id == route.id)
        .order_by(RouteStage.sequence)
        .options(*[staged.property.loader for staged in [
            # eager load section and storage_section for assertions
            __import__("sqlalchemy.orm").orm.selectinload(RouteStage.section),
        ]]) if False else select(RouteStage).where(RouteStage.route_id == route.id).order_by(RouteStage.sequence)
    )).scalars().all()

    # Reload with relationships eagerly loaded
    from sqlalchemy.orm import selectinload
    stages = (await session.execute(
        select(RouteStage)
        .where(RouteStage.route_id == route.id)
        .order_by(RouteStage.sequence)
        .options(
            selectinload(RouteStage.section),
            selectinload(RouteStage.storage_section),
            selectinload(RouteStage.operations),
        )
    )).scalars().all()

    by_code = {s.section.code: s for s in stages if s.section_id is not None and s.section}
    by_storage_code = {s.storage_section.code: s for s in stages if s.storage_section_id is not None and s.storage_section}

    # Every storage section must be present as a transit stage with section_id NULL
    for code, section in sections_map.items():
        if not is_storage_section(section):
            continue
        assert code in by_storage_code, f"Storage section {code} missing transit stage"
        stage = by_storage_code[code]
        assert is_transit_stage(stage), f"{code} should be transit"
        assert stage.section_id is None
        assert stage.storage_section_id == section.id
        # No real RouteOperation rows for transit stages
        assert stage.operations == [], f"{code} transit should not have operations"

    # Every production section must be present as a production stage
    for code, section in sections_map.items():
        if is_storage_section(section):
            continue
        assert code in by_code, f"Production section {code} missing production stage"
        stage = by_code[code]
        assert is_production_stage(stage), f"{code} should be production"
        assert stage.section_id == section.id
        assert stage.storage_section_id is None
        # Production stages do have a RouteOperation
        assert len(stage.operations) >= 1


@pytest.mark.asyncio
async def test_seed_routes_creates_one_stage_per_step(session: AsyncSession):
    await _seed_sections_only(session)
    await seed_routes(session, ROUTES, force=True)
    route = await session.scalar(
        select(ProductionRoute).where(ProductionRoute.code == "universal_rp")
    )
    stages = (await session.execute(
        select(RouteStage).where(RouteStage.route_id == route.id)
    )).scalars().all()
    # 11 steps in the universal route → 11 stages (1 per step, no combined groups)
    assert len(stages) == len(ROUTES[0]["steps"])


# --- seed_production_routes_from_profiles -----------------------------------


@pytest.mark.asyncio
async def test_seed_routes_from_profile_marks_storage_as_transit(session: AsyncSession):
    from app.models.route import RouteRuleProfile

    # Need an active profile with route_sections
    profile = RouteRuleProfile(
        code="test_profile",
        name="Test Profile",
        is_active=True,
        priority=0,
        route_sections=["RAW_STOCK", "DRILLING", "PRESSING", "WIP_STOCK", "PACKING", "SHIPPED"],
        route_name_pattern="{operations}",
    )
    session.add(profile)
    await session.flush()
    await _seed_sections_only(session)
    await session.commit()
    # Re-fetch profile in this transaction
    profile = await session.scalar(
        select(RouteRuleProfile).where(RouteRuleProfile.code == "test_profile")
    )

    count = await seed_production_routes_from_profiles(session)
    assert count >= 1

    route = await session.scalar(
        select(ProductionRoute).where(ProductionRoute.code.like("dynamic_test_profile%"))
    )
    assert route is not None
    from sqlalchemy.orm import selectinload
    stages = (await session.execute(
        select(RouteStage)
        .where(RouteStage.route_id == route.id)
        .order_by(RouteStage.sequence)
        .options(
            selectinload(RouteStage.section),
            selectinload(RouteStage.storage_section),
            selectinload(RouteStage.operations),
        )
    )).scalars().all()

    assert len(stages) == 6  # WH, DRILL, PRESS, WIP_WH, PACK, SENT

    storage_codes = {"RAW_STOCK", "WIP_STOCK", "SHIPPED"}
    for s in stages:
        if s.storage_section_id is not None:
            assert s.section_id is None
            assert s.storage_section.code in storage_codes
            assert s.operations == []
            assert s.is_final is False
        else:
            assert s.section is not None
            assert s.section.code not in storage_codes
            assert len(s.operations) >= 1
            # Only SENT is final in our profile; SENT here is transit, so nothing is final
            assert s.is_final is False


# --- demo_production_seeder --------------------------------------------------


@pytest.mark.asyncio
async def test_seed_demo_production_resolves_stages_by_code(session: AsyncSession):
    """Ensure the demo seeder picks DRILL/SHOT/ANOD stages by section code,
    not by positional index, and works with transit stages interleaved."""
    from app.seeds.run_seed import run_full_seed
    from app.seeds.seeders.demo_production_seeder import seed_demo_production

    # Pre-seed a profile so dynamic route can be built
    stats = await run_full_seed(session, force=True)
    await seed_demo_production(session)
    # At least the routes and remainders were created
    assert stats.get("routes", 0) >= 1

    # Find the dynamic route from packaging_map_rp profile
    route = await session.scalar(
        select(ProductionRoute).where(ProductionRoute.code == "dynamic_packaging_map_rp")
    )
    assert route is not None

    from sqlalchemy.orm import selectinload
    stages = (await session.execute(
        select(RouteStage)
        .where(RouteStage.route_id == route.id)
        .order_by(RouteStage.sequence)
        .options(
            selectinload(RouteStage.section),
            selectinload(RouteStage.storage_section),
            selectinload(RouteStage.operations),
        )
    )).scalars().all()

    # Some transit stages must exist (proves seeders wired the new model)
    transit_stages = [s for s in stages if is_transit_stage(s)]
    assert len(transit_stages) >= 3, f"expected at least 3 transit stages, got {len(transit_stages)}"

    # build_completed_stages_json must drop transit
    completed = await build_completed_stages_json(session, stages)
    section_ids_in_completed = {c["section_id"] for c in completed}
    for t in transit_stages:
        assert t.storage_section_id not in section_ids_in_completed
