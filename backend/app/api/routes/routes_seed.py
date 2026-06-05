"""Seed endpoint — fills ALL reference data in one shot:
ImportTemplate + RouteRuleProfile + Routes + SelectionRules."""

import logging

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import WRITER_ROLES, require_role
from app.core.config import settings
from app.core.database import get_db
from app.seeds.run_seed import run_full_seed
from app.seeds.seeders.users_seeder import seed_users
from app.seeds.seeders.demo_production_seeder import seed_demo_production
from app.seeds.seeders.cleanup_seeder import clear_generated_production_data

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/routes-seed", tags=["routes-seed"])


class SeedSummary(BaseModel):
    import_templates: int
    route_rule_profiles: int
    routes: int
    selection_rules: int
    sections: int
    section_operations: int


class UserSeedResult(BaseModel):
    user_id: int
    email: str


@router.post("/reseed-system-user", response_model=UserSeedResult, dependencies=[Depends(require_role(list(WRITER_ROLES)))])
async def reseed_system_user(db: AsyncSession = Depends(get_db)) -> UserSeedResult:
    """Delete and recreate system user with id=1. Ensures FK constraints work with _fake_user()."""
    try:
        result = await seed_users(db)
        await db.commit()
        user_id, user = next(iter(result.items()))
        return UserSeedResult(user_id=user_id, email=user.email)
    except Exception as e:
        await db.rollback()
        logger.exception("Reseed system user failed")
        raise HTTPException(status_code=500, detail=str(e))


class SeedPreview(BaseModel):
    """Counts that would be created from seed files (without touching DB)."""
    import_templates: int
    route_rule_profiles: int
    routes: int
    selection_rules: int
    sections: int
    section_operations: int


@router.get("/preview", response_model=SeedPreview)
async def seed_preview() -> SeedPreview:
    """Return counts from seed files without touching the database."""
    from app.seeds.import_templates import IMPORT_TEMPLATES
    from app.seeds.route_rule_profiles import ROUTE_RULE_PROFILES
    from app.seeds.routes import ROUTES
    from app.seeds.selection_rules import SELECTION_RULES

    # Sections and operations are defined in the seeder itself
    from app.seeds.seeders.sections_seeder import SECTIONS_DATA, SECTION_OPS

    # Count total operations (skip None placeholders)
    total_ops = sum(
        1 for ops in SECTION_OPS.values()
        for op in ops
        if op[3] is not None  # op_code is index 3
    )

    return SeedPreview(
        import_templates=len(IMPORT_TEMPLATES),
        route_rule_profiles=len(ROUTE_RULE_PROFILES),
        # Static routes + 1 dynamic route per profile with route_sections
        routes=len(ROUTES) + sum(1 for p in ROUTE_RULE_PROFILES if p.get("route_sections")),
        selection_rules=len(SELECTION_RULES),
        sections=len(SECTIONS_DATA),
        section_operations=total_ops,
    )


@router.post("", response_model=SeedSummary, status_code=status.HTTP_201_CREATED)
async def seed_all(
    force: bool = Query(False, description="Force replace routes and dependent data"),
    db: AsyncSession = Depends(get_db),
) -> SeedSummary:
    """Seed all reference data: templates, profiles, routes, selection rules."""
    if force and settings.ENV in ("prod", "production"):
        raise HTTPException(status_code=403, detail="force=true is not allowed in production")
    try:
        result = await run_full_seed(db, force=force)
        await db.commit()
        return SeedSummary(
            import_templates=result["import_templates"],
            route_rule_profiles=result["route_rule_profiles"],
            routes=result["routes"],
            selection_rules=result["selection_rules"],
            sections=result["sections"],
            section_operations=result["section_operations"],
        )
    except RuntimeError as e:
        await db.rollback()
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        logger.exception("Seed failed")
        await db.rollback()
        raise HTTPException(status_code=500, detail=str(e))


class DemoSeedSummary(BaseModel):
    products: int
    remainders: int
    defects: int


@router.post("/demo-production", response_model=DemoSeedSummary, status_code=status.HTTP_201_CREATED)
async def seed_demo_production_endpoint(
    db: AsyncSession = Depends(get_db),
) -> DemoSeedSummary:
    """Seed only demo production data (remainders, stages, defects)."""
    try:
        stats = await seed_demo_production(db)
        await db.commit()
        return DemoSeedSummary(
            products=stats.get("products", 0),
            remainders=stats.get("remainders", 0),
            defects=stats.get("defects", 0),
        )
    except Exception as e:
        logger.exception("Demo seed failed")
        await db.rollback()
        raise HTTPException(status_code=500, detail=str(e))


class ClearSummary(BaseModel):
    cleanup: dict


@router.post("/clear-demo-production", response_model=ClearSummary)
async def clear_demo_production_endpoint(
    db: AsyncSession = Depends(get_db),
) -> ClearSummary:
    """Clear generated production data (remainders, defects, tasks, etc.)."""
    try:
        stats = await clear_generated_production_data(db)
        await db.commit()
        return ClearSummary(cleanup=stats)
    except Exception as e:
        logger.exception("Clear production data failed")
        await db.rollback()
        raise HTTPException(status_code=500, detail=str(e))
