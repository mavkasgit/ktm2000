from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.services.plan_generation import get_release_batch_summary, release_batch

router = APIRouter(prefix="/release-batches", tags=["release-batches"])


@router.get("/{release_batch_id}")
async def get_release_batch(release_batch_id: int, db: AsyncSession = Depends(get_db)) -> dict:
    try:
        return await get_release_batch_summary(db, release_batch_id)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.post("/{release_batch_id}/release")
async def release_release_batch(release_batch_id: int, db: AsyncSession = Depends(get_db)) -> dict:
    try:
        return await release_batch(db, release_batch_id)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
