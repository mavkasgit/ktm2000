"""Seed endpoint — fills ALL reference data in one shot:
ImportTemplate + RouteRuleProfile + Routes + SelectionRules."""

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.database import get_db
from app.seeds.run_seed import run_full_seed

router = APIRouter(prefix="/routes-seed", tags=["routes-seed"])


class SeedSummary(BaseModel):
    import_templates: int
    route_rule_profiles: int
    routes: int
    selection_rules: int


@router.post("", response_model=SeedSummary, status_code=status.HTTP_201_CREATED)
async def seed_all(
    force: bool = Query(False, description="Force replace routes and dependent data"),
    db: AsyncSession = Depends(get_db),
) -> SeedSummary:
    """Seed all reference data: templates, profiles, routes, selection rules."""
    if force and settings.ENV == "production":
        raise HTTPException(status_code=403, detail="force=true is not allowed in production")
    try:
        result = await run_full_seed(db, force=force)
        await db.commit()
        return SeedSummary(
            import_templates=result["import_templates"],
            route_rule_profiles=result["route_rule_profiles"],
            routes=result["routes"],
            selection_rules=result["selection_rules"],
        )
    except RuntimeError as e:
        await db.rollback()
        raise HTTPException(status_code=400, detail=str(e))
    except Exception:
        await db.rollback()
        raise HTTPException(status_code=500, detail="Seed failed")
