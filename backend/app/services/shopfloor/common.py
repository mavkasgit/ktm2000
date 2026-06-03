from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.defect import Defect
from app.models.route import RouteStage
from app.models.transfer import Transfer
from app.models.user import User
from app.models.work_task import WorkTask

def _to_decimal(value: Decimal | int | float | str) -> Decimal:
    return Decimal(str(value))

def _ensure_positive(value: Decimal, field_name: str) -> None:
    if value <= 0:
        raise ValueError(f"{field_name} must be > 0")

async def _get_task(db: AsyncSession, task_id: int) -> WorkTask:
    task = await db.get(WorkTask, task_id)
    if task is None:
        raise ValueError("Task not found")
    return task

async def _get_transfer(db: AsyncSession, transfer_id: int) -> Transfer:
    transfer = await db.get(Transfer, transfer_id)
    if transfer is None:
        raise ValueError("Transfer not found")
    return transfer

async def _get_defect(db: AsyncSession, defect_id: int) -> Defect:
    defect = await db.get(Defect, defect_id)
    if defect is None:
        raise ValueError("Defect not found")
    return defect

async def _check_idempotency(
    db: AsyncSession,
    *,
    idempotency_key: str | None,
    entity_type: type,
) -> object | None:
    """Return existing entity if idempotency_key was already used, else None."""
    if not idempotency_key:
        return None
    return await db.scalar(
        select(entity_type).where(entity_type.idempotency_key == idempotency_key)
    )

async def _get_route_stage(db: AsyncSession, route_stage_id: int) -> RouteStage:
    stage = await db.get(RouteStage, route_stage_id)
    if stage is None:
        raise ValueError("Route stage not found")
    return stage

def _transfer_no() -> str:
    return f"TR-{datetime.now(UTC).strftime('%Y%m%d%H%M%S%f')}"


async def _get_user_snapshot_name(db: AsyncSession, user_id: int | None) -> str | None:
    """Look up a user's display name (full_name, falling back to email) for snapshot purposes.

    Returns None if user_id is None or the user doesn't exist (e.g., legacy data).
    """
    if user_id is None:
        return None
    user = await db.get(User, user_id)
    if user is None:
        return None
    return user.full_name or user.email

