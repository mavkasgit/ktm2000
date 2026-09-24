from datetime import date, datetime
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import READER_ROLES, WRITER_ROLES, get_current_user, get_db, require_role
from app.models.user import User
from app.services.daily_plan_service import (
    DailyPlanConflict,
    DailyPlanNotFound,
    create_plan,
    list_items,
    list_plans_for_section,
    revoke_item,
)

router = APIRouter(prefix="/daily-plans", tags=["daily-plans"])


class DailyPlanCreate(BaseModel):
    section_id: int
    plan_date: date
    work_task_ids: list[int] = Field(default_factory=list)

class DailyPlanOut(BaseModel):
    id: int
    section_id: int
    plan_date: date
    created_at: datetime
    created_by: int
    item_count: int
    progress_percent: int


class DailyPlanItemsOut(BaseModel):
    items: list[dict[str, Any]]


class DailyPlanRevokeOut(BaseModel):
    plan_id: int
    work_task_id: int


@router.get("/sections/{section_id}", response_model=list[DailyPlanOut])
async def get_section_daily_plans(
    section_id: int,
    db: AsyncSession = Depends(get_db),
    _: User = Depends(require_role(READER_ROLES)),
) -> list[dict[str, Any]]:
    return await list_plans_for_section(db, section_id)



@router.post("", response_model=DailyPlanOut, status_code=status.HTTP_201_CREATED)
async def post_daily_plan(
    payload: DailyPlanCreate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_role(WRITER_ROLES)),
) -> dict[str, Any]:
    try:
        return await create_plan(
            db,
            section_id=payload.section_id,
            plan_date=payload.plan_date,
            work_task_ids=payload.work_task_ids,
            created_by=current_user.id,
        )
    except DailyPlanConflict as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc
    except IntegrityError as exc:
        await db.rollback()
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="work task already belongs to a daily plan") from exc
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc)) from exc


@router.get("/{plan_id}/items", response_model=DailyPlanItemsOut)
async def get_daily_plan_items(
    plan_id: int,
    db: AsyncSession = Depends(get_db),
    _: User = Depends(require_role(READER_ROLES)),
) -> DailyPlanItemsOut:
    try:
        return DailyPlanItemsOut(items=await list_items(db, plan_id))
    except DailyPlanNotFound as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc


@router.post("/{plan_id}/items/{work_task_id}/revoke", response_model=DailyPlanRevokeOut)
async def post_daily_plan_revoke(
    plan_id: int,
    work_task_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_role(WRITER_ROLES)),
) -> DailyPlanRevokeOut:
    try:
        return DailyPlanRevokeOut(**await revoke_item(db, plan_id=plan_id, work_task_id=work_task_id, user=current_user))
    except DailyPlanNotFound as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc
