from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal
from typing import Iterable

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.defect import Defect
from app.models.route import RouteStage, SectionOperation
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


async def _significant_section_ids(
    db: AsyncSession,
    section_ids: Iterable[int],
) -> set[int]:
    """Return the subset of section_ids that are «significant» (i.e. real production work).

    Two rules, in priority order:

    1. If a section has at least one :class:`SectionOperation` row, it is significant iff
       any of those operations carries ``is_significant=True``. This is the canonical
       production-data path (WH→ISSUE_RAW, WIP_WH→MOVE_TO_WIP, FG_WH/SHIPMENT/SENT are
       therefore filtered out; DRILL/PRESS/SHOT/ANOD/PACK are kept).

    2. If a section has no :class:`SectionOperation` rows at all (legacy data, or
       tests that build ad-hoc sections), fall back to ``Section.kind``:
       ``production`` sections are kept, ``raw_stock``/``wip_stock``/``finished_stock``
       sections are filtered out. This keeps the helper robust without forcing every
       fixture to declare SectionOperation rows.
    """
    ids = {int(s) for s in section_ids}
    if not ids:
        return set()

    sig_ops_rows = (
        await db.execute(
            select(SectionOperation.section_id)
            .where(SectionOperation.section_id.in_(ids))
            .where(SectionOperation.is_significant.is_(True))
            .distinct()
        )
    ).scalars().all()
    with_sig_ops = {int(r) for r in sig_ops_rows}

    sections_with_any_op = {
        int(r) for r in (
            await db.execute(
                select(SectionOperation.section_id)
                .where(SectionOperation.section_id.in_(ids))
                .distinct()
            )
        ).scalars().all()
    }

    # Sections without ANY SectionOperation fall back to kind-based classification
    no_ops_ids = ids - sections_with_any_op
    fallback_keep: set[int] = set()
    if no_ops_ids:
        from app.models.section import Section
        rows = (
            await db.execute(
                select(Section.id, Section.kind).where(Section.id.in_(no_ops_ids))
            )
        ).all()
        for sec_id, kind in rows:
            if kind == "production":
                fallback_keep.add(int(sec_id))

    return with_sig_ops | fallback_keep


async def build_completed_stages_json(
    db: AsyncSession,
    stages: Iterable[RouteStage],
) -> list[dict]:
    """Build ``completed_stages_json`` payload, skipping non-significant (pass-through) stages.

    For each input stage we emit a dict ``{section_id, operation_code, operation_name, sequence}``
    iff the stage's section is classified as «significant» (see
    :func:`_significant_section_ids`). Pass-through sections (warehouse issue, WIP
    transfers, FG warehouse, shipment, sent) are dropped so the snapshot focuses on
    real production work.
    """
    stage_list = list(stages)
    if not stage_list:
        return []
    significant = await _significant_section_ids(
        db, [s.section_id for s in stage_list]
    )
    result: list[dict] = []
    for s in stage_list:
        if s.section_id not in significant:
            continue
        result.append({
            "section_id": s.section_id,
            "operation_code": s.operations[0].operation_code if s.operations else None,
            "operation_name": ", ".join(op.operation_name for op in s.operations) if s.operations else "",
            "sequence": s.sequence,
        })
    return result

