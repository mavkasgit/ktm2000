"""FastAPI router for the transfer module.

Mounted at ``/transfers``.  Provides:

  * ``POST /transfers``                          — send a transfer
  * ``POST /transfers/{id}/accept``              — accept (or reject) a transfer
  * ``POST /transfers/{id}/discrepancies/{d}/resolve-link``  — link a discrepancy to a DefectItem
  * ``GET  /transfers/{id}``                     — transfer details (with discrepancies)
  * ``GET  /transfers/ready``                    — list of SectionTasks ready to transfer
  * ``GET  /transfers/sections/{id}/incoming``   — incoming open transfers for a section

Compatibility: the legacy ``/shopfloor/transfers`` endpoints are kept
working as thin proxies in ``app.api.routes.shopfloor`` so the
existing UI keeps functioning during the migration.
"""

from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Header, Query
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import READER_ROLES, WRITER_ROLES, require_role
from app.api.deps import get_current_user
from app.core.database import get_db
from app.models.transfer import Transfer
from app.models.user import User
from app.models.work_task import WorkTask

from app.transfers.queries import (
    get_section_incoming_transfers,
    get_transfer_details,
    list_ready_to_transfer,
)
from app.transfers.schemas import (
    AcceptTransferPayload,
    CreateTransferPayload,
    ResolveDiscrepancyPayload,
)
from app.transfers.services import (
    resolve_transfer_discrepancy_link,
    transfer_receive,
    transfer_send,
)

router = APIRouter(prefix="/transfers", tags=["transfers"])

LOCKED_SECTION_ERROR = "Section is locked to single-window context"


def get_single_window_locked_section_id(
    x_shopfloor_single_section_id: int | None = Header(default=None, alias="X-Shopfloor-Single-Section-Id"),
) -> int | None:
    return x_shopfloor_single_section_id


async def _ensure_task_lock(db: AsyncSession, task_id: int, locked_section_id: int | None) -> None:
    if locked_section_id is None:
        return
    task_section_id = await db.scalar(
        select(WorkTask.section_id).where(WorkTask.id == task_id)
    )
    if task_section_id is not None and task_section_id != locked_section_id:
        raise HTTPException(status_code=403, detail=LOCKED_SECTION_ERROR)


async def _ensure_transfer_target_lock(
    db: AsyncSession, transfer_id: int, locked_section_id: int | None
) -> None:
    if locked_section_id is None:
        return
    transfer_target_section_id = await db.scalar(
        select(Transfer.to_section_id).where(Transfer.id == transfer_id)
    )
    if transfer_target_section_id is not None and transfer_target_section_id != locked_section_id:
        raise HTTPException(status_code=403, detail=LOCKED_SECTION_ERROR)


@router.post("", dependencies=[Depends(require_role(list(WRITER_ROLES)))])
async def create_transfer(
    payload: CreateTransferPayload,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
    locked_section_id: int | None = Depends(get_single_window_locked_section_id),
) -> dict:
    """Send quantity from a completed SectionTask to the next route step.

    The source task is treated as a single unit: it may already
    represent multiple route operations merged via
    ``combined_op_group`` at plan-generation time, but no further
    splitting happens at transfer time.
    """
    await _ensure_task_lock(db, payload.from_task_id, locked_section_id)
    try:
        return await transfer_send(
            db,
            from_task_id=payload.from_task_id,
            to_task_id=payload.to_task_id,
            quantity=payload.quantity,
            actor_id=current_user.id,
            comment=payload.comment,
            idempotency_key=payload.idempotency_key,
            executor_user_id=payload.executor_user_id,
            performed_at=payload.performed_at,
            accounted_at=payload.accounted_at,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.get("/ready", dependencies=[Depends(require_role(list(READER_ROLES)))])
async def ready_to_transfer(
    section_id: Optional[int] = Query(default=None),
    spg_id: Optional[int] = Query(default=None),
    db: AsyncSession = Depends(get_db),
    locked_section_id: int | None = Depends(get_single_window_locked_section_id),
) -> dict:
    """List SectionTasks that have quantity ready to be sent to the next step.

    Pass exactly one of ``section_id`` or ``spg_id``; ``spg_id`` wins if
    both are given.  Honours single-window locking when ``section_id``
    is given.
    """
    if locked_section_id is not None and section_id is None:
        section_id = locked_section_id
    if locked_section_id is not None and section_id != locked_section_id:
        raise HTTPException(status_code=403, detail=LOCKED_SECTION_ERROR)
    return await list_ready_to_transfer(db, section_id=section_id, spg_id=spg_id)


@router.get(
    "/sections/{section_id}/incoming",
    dependencies=[Depends(require_role(list(READER_ROLES)))],
)
async def incoming_transfers(
    section_id: int,
    db: AsyncSession = Depends(get_db),
    locked_section_id: int | None = Depends(get_single_window_locked_section_id),
) -> dict:
    if locked_section_id is not None and section_id != locked_section_id:
        raise HTTPException(status_code=403, detail=LOCKED_SECTION_ERROR)
    return await get_section_incoming_transfers(db, section_id=section_id)


@router.post("/{transfer_id}/accept", dependencies=[Depends(require_role(list(WRITER_ROLES)))])
async def accept_transfer(
    transfer_id: int,
    payload: AcceptTransferPayload,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
    locked_section_id: int | None = Depends(get_single_window_locked_section_id),
) -> dict:
    await _ensure_transfer_target_lock(db, transfer_id, locked_section_id)
    try:
        return await transfer_receive(
            db,
            transfer_id=transfer_id,
            accepted_quantity=payload.accepted_quantity,
            rejected_quantity=payload.rejected_quantity,
            actor_id=current_user.id,
            reason=payload.reason,
            comment=payload.comment,
            idempotency_key=payload.idempotency_key,
            executor_user_id=payload.executor_user_id,
            performed_at=payload.performed_at,
            accounted_at=payload.accounted_at,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post(
    "/{transfer_id}/discrepancies/{discrepancy_id}/resolve-link",
    dependencies=[Depends(require_role(list(WRITER_ROLES)))],
)
async def resolve_discrepancy(
    transfer_id: int,
    discrepancy_id: int,
    payload: ResolveDiscrepancyPayload,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> dict:
    try:
        return await resolve_transfer_discrepancy_link(
            db,
            transfer_id=transfer_id,
            discrepancy_id=discrepancy_id,
            defect_item_id=payload.defect_item_id,
            quantity=payload.quantity,
            actor_id=current_user.id,
            comment=payload.comment,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.get("/{transfer_id}", dependencies=[Depends(require_role(list(READER_ROLES)))])
async def transfer_details(transfer_id: int, db: AsyncSession = Depends(get_db)) -> dict:
    try:
        return await get_transfer_details(db, transfer_id)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
