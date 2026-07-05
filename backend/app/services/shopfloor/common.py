from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal
from typing import Iterable

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


async def _get_task_for_update(db: AsyncSession, task_id: int) -> WorkTask:
    """Load a WorkTask with a row-level lock (SELECT ... FOR UPDATE).

    Use this in write paths that need to serialise concurrent mutations
    of the same task (e.g. concurrent transfer_send calls would otherwise
    each see the same stale ``cached_transferred_quantity`` and both pass
    the ``quantity <= transferable`` guard).
    """
    task = (
        await db.scalar(
            select(WorkTask).where(WorkTask.id == task_id).with_for_update()
        )
    )
    if task is None:
        raise ValueError("Task not found")
    return task

async def _get_transfer_for_update(db: AsyncSession, transfer_id: int) -> Transfer:
    """Load a Transfer with a row-level lock (SELECT ... FOR UPDATE).

    Serialises concurrent accept/correct/cancel on the same transfer so
    that ``accepted + rejected <= sent`` cannot be violated by parallel
    writes.
    """
    transfer = (
        await db.scalar(
            select(Transfer).where(Transfer.id == transfer_id).with_for_update()
        )
    )
    if transfer is None:
        raise ValueError("Transfer not found")
    return transfer


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
    if not user_id:
        return None
    user = await db.get(User, user_id)
    if user is None:
        return None
    return user.full_name or user.email


async def sections_share_spg(db: AsyncSession, section_id_1: int, section_id_2: int) -> bool:
    """Check if both sections share the same Storage Production Group (GHP/SPG)."""
    if section_id_1 == section_id_2:
        return True

    from app.models.spg import SpgSection

    spg_1 = await db.scalar(select(SpgSection.spg_id).where(SpgSection.section_id == section_id_1))
    if spg_1 is None:
        return False

    spg_2 = await db.scalar(select(SpgSection.spg_id).where(SpgSection.section_id == section_id_2))
    return spg_1 == spg_2


async def build_completed_stages_json(
    db: AsyncSession,
    stages: Iterable[RouteStage],
) -> list[dict]:
    """Build ``completed_stages_json`` payload, skipping transit (pass-through) stages.

    For each ``production`` stage we emit a dict ``{section_id, operation_code,
    operation_name, sequence}``.  Transit stages (``stage_kind='transit'`` — i.e.
    warehouse hops) are dropped so the snapshot focuses on real production work.

    Decision is made by :mod:`app.services.route_storage_classifier`, which is the
    single source of truth for «это цех или склад» across the codebase.
    """
    from sqlalchemy.orm import selectinload

    from app.services.route_storage_classifier import classify_stages, is_transit_stage

    stage_list = list(stages)
    if not stage_list:
        return []
    production_stages, _transit = await classify_stages(db, stage_list)
    # Ensure operations relationship is loaded for production stages we will serialise
    prod_ids = [s.id for s in production_stages if s.id is not None]
    if prod_ids:
        loaded = (await db.execute(
            select(RouteStage)
            .options(selectinload(RouteStage.operations))
            .where(RouteStage.id.in_(prod_ids))
        )).scalars().all()
        loaded_by_id = {s.id: s for s in loaded}
        production_stages = [loaded_by_id.get(s.id, s) for s in production_stages]
    result: list[dict] = []
    for s in production_stages:
        if is_transit_stage(s):
            continue
        result.append({
            "section_id": s.section_id,
            "operation_code": s.operations[0].operation_code if s.operations else None,
            "operation_name": ", ".join(op.operation_name for op in s.operations) if s.operations else "",
            "sequence": s.sequence,
        })
    return result


def format_operations_comment_suffix(stages: list[dict]) -> str:
    """Return ``| операции: ...`` suffix for stock transaction comments."""
    if not stages:
        return ""
    ops_names = ", ".join(
        s["operation_name"]
        for s in stages
        if s.get("operation_name")
    )
    if not ops_names:
        return ""
    return f" | операции: {ops_names}"


def append_operations_to_comment(comment: str | None, stages: list[dict]) -> str | None:
    """Append completed-operations suffix to an existing transaction comment."""
    suffix = format_operations_comment_suffix(stages)
    if not suffix:
        return comment
    return f"{comment or ''}{suffix}"


async def build_operations_comment_suffix_for_route(
    db: AsyncSession,
    *,
    route_id: int,
    through_sequence: int,
) -> str:
    """Build operations suffix for route stages up to ``through_sequence`` (inclusive)."""
    stages = (
        await db.execute(
            select(RouteStage)
            .where(
                RouteStage.route_id == route_id,
                RouteStage.sequence <= through_sequence,
            )
            .order_by(RouteStage.sequence)
        )
    ).scalars().all()
    completed = await build_completed_stages_json(db, stages)
    return format_operations_comment_suffix(completed)


async def enrich_comment_with_route_operations(
    db: AsyncSession,
    comment: str | None,
    *,
    route_id: int,
    through_sequence: int,
) -> str | None:
    """Append route-progress operations suffix to a stock transaction comment."""
    suffix = await build_operations_comment_suffix_for_route(
        db,
        route_id=route_id,
        through_sequence=through_sequence,
    )
    if not suffix:
        return comment
    return f"{comment or ''}{suffix}"
