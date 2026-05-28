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
