from decimal import Decimal

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.models.production_plan import PlanChangeSet
from app.models.release_batch import ReleaseBatchType
from app.services.plan_generation import create_release_batch
from app.services.production_plan_service import apply_change_set, approve_plan_position, get_plan_preview, rollback_change_set

router = APIRouter(prefix="/production-plans", tags=["production-plans"])


class ReleasePositionIn(BaseModel):
    plan_position_id: int
    release_quantity: Decimal | None = None


class ReleaseBatchCreateIn(BaseModel):
    name: str | None = None
    batch_type: ReleaseBatchType = ReleaseBatchType.manual
    positions: list[ReleasePositionIn] | None = None


@router.get("/{production_plan_id}/preview")
async def preview_production_plan(production_plan_id: int, db: AsyncSession = Depends(get_db)) -> dict:
    try:
        return await get_plan_preview(db, production_plan_id)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.post("/{production_plan_id}/change-sets/{change_set_id}/apply")
async def apply_plan_change_set(
    production_plan_id: int,
    change_set_id: int,
    db: AsyncSession = Depends(get_db),
) -> dict:
    change_set = await db.get(PlanChangeSet, change_set_id)
    if change_set is None:
        raise HTTPException(status_code=404, detail="Change set not found")
    if change_set.production_plan_id != production_plan_id:
        raise HTTPException(status_code=400, detail="Change set does not belong to production plan")
    try:
        preview = await apply_change_set(db, change_set_id)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return preview


@router.post("/{production_plan_id}/change-sets/{change_set_id}/rollback")
async def rollback_plan_change_set(
    production_plan_id: int,
    change_set_id: int,
    db: AsyncSession = Depends(get_db),
) -> dict:
    change_set = await db.get(PlanChangeSet, change_set_id)
    if change_set is None:
        raise HTTPException(status_code=404, detail="Change set not found")
    if change_set.production_plan_id != production_plan_id:
        raise HTTPException(status_code=400, detail="Change set does not belong to production plan")
    try:
        return await rollback_change_set(db, change_set_id)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post("/{production_plan_id}/positions/{position_id}/approve")
async def approve_position(
    production_plan_id: int,
    position_id: int,
    db: AsyncSession = Depends(get_db),
) -> dict:
    try:
        position = await approve_plan_position(db, production_plan_id, position_id)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return {
        "id": position.id,
        "production_plan_id": position.production_plan_id,
        "status": position.status.value,
        "validation_status": position.validation_status.value,
        "validation_errors": position.validation_errors,
    }


@router.post("/{production_plan_id}/release-batches", status_code=status.HTTP_201_CREATED)
async def create_plan_release_batch(
    production_plan_id: int,
    payload: ReleaseBatchCreateIn,
    db: AsyncSession = Depends(get_db),
) -> dict:
    try:
        return await create_release_batch(
            db,
            production_plan_id=production_plan_id,
            positions=[item.model_dump() for item in payload.positions] if payload.positions else None,
            batch_type=payload.batch_type,
            name=payload.name,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
