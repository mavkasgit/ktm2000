"""FastAPI router for the transfer module.

Mounted at ``/transfers``.  Provides:

  * ``POST /transfers``                          — send a transfer (auto-accepts)
  * ``GET  /transfers/{id}``                     — transfer details
  * ``GET  /transfers/ready``                    — list of SectionTasks ready to transfer
  * ``GET  /transfers/sections/{id}/incoming``   — incoming open transfers for a section
  * ``PUT  /transfers/{id}``                     — correct an accepted transfer
  * ``POST /transfers/{id}/cancel``               — cancel an accepted transfer

Under the explicit-transfer model, ``POST /transfers`` is the single
write path. The auto-accept (receive) is part of the service itself,
so the destination task transitions to ``ready`` and the receive
Movement is written by the time the API returns. There is no separate
``/transfers/{id}/accept`` endpoint anymore.

Compatibility: the legacy ``/shopfloor/transfers`` endpoints are kept
working as thin proxies in ``app.api.routes.shopfloor`` so the
existing UI keeps functioning during the migration.
"""

from __future__ import annotations

from datetime import datetime
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import (
    READER_ROLES,
    TRANSFER_WRITER_ROLES,
    _ensure_section_lock,
    _ensure_task_lock,
    get_current_user,
    get_single_window_locked_section_id,
    require_role,
)
from app.core.database import get_db
from app.domain.dimensions import DimensionsValidationError
from app.models.user import User

from app.transfers.queries import (
    get_section_incoming_transfers,
    get_transfer_details,
    list_ready_to_transfer,
    get_section_transfer_history,
)
from app.transfers.schemas import (
    CreateTransferPayload,
    CorrectTransferPayload,
)
from app.transfers.services import (
    transfer_send,
    correct_transfer,
    cancel_transfer,
)

router = APIRouter(prefix="/transfers", tags=["transfers"])


@router.post("", dependencies=[Depends(require_role(list(TRANSFER_WRITER_ROLES)))])
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

    Under the explicit-transfer model, ``transfer_send`` itself
    auto-accepts: by the time this endpoint returns, the destination
    task has transitioned to ``ready`` and the receive Movement is
    written. There is no separate accept step.
    """
    await _ensure_task_lock(db, payload.from_task_id, locked_section_id, current_user)
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
            post_factum=payload.post_factum,
            allow_over_plan=payload.allow_over_plan,
            physical_handover_at=payload.physical_handover_at,
            dimensions=payload.dimensions,
        )
    except DimensionsValidationError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.get("/ready", dependencies=[Depends(require_role(list(READER_ROLES)))])
async def ready_to_transfer(
    section_id: Optional[int] = Query(default=None),
    spg_id: Optional[int] = Query(default=None),
    limit: int = Query(default=50, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
    search: str | None = Query(default=None),
    sort_by: str = Query(default="sequence"),
    sort_order: str = Query(default="asc"),
    product_sku: str | None = Query(default=None),
    operation_name: str | None = Query(default=None),
    next_operation_name: str | None = Query(default=None),
    next_section_name: str | None = Query(default=None),
    task_id: int | None = Query(default=None),
    plan_position_id: int | None = Query(default=None),
    transferable_qty: str | None = Query(default=None),
    dimensions: str | None = Query(
        default=None,
        description='Column filter: exact JSON match on task dimensions, e.g. {"length_mm":2700} or null',
    ),
    db: AsyncSession = Depends(get_db),
    locked_section_id: int | None = Depends(get_single_window_locked_section_id),
) -> dict:
    """List SectionTasks that have quantity ready to be sent to the next step.

    Pass exactly one of ``section_id`` or ``spg_id``; ``spg_id`` wins if
    both are given.  Honours single-window locking when ``section_id``
    is given.
    """
    from app.domain.dimensions import DimensionsValidationError, parse_dimensions_filter

    try:
        parse_dimensions_filter(dimensions)
    except DimensionsValidationError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    if locked_section_id is not None and section_id is None:
        section_id = locked_section_id
    _ensure_section_lock(section_id, locked_section_id)
    return await list_ready_to_transfer(
        db,
        section_id=section_id,
        spg_id=spg_id,
        limit=limit,
        offset=offset,
        search=search,
        sort_by=sort_by,
        sort_order=sort_order,
        product_sku=product_sku,
        operation_name=operation_name,
        next_operation_name=next_operation_name,
        next_section_name=next_section_name,
        task_id=task_id,
        plan_position_id=plan_position_id,
        transferable_qty=transferable_qty,
        dimensions=dimensions,
    )


@router.get(
    "/sections/{section_id}/incoming",
    dependencies=[Depends(require_role(list(READER_ROLES)))],
)
async def incoming_transfers(
    section_id: int,
    db: AsyncSession = Depends(get_db),
    locked_section_id: int | None = Depends(get_single_window_locked_section_id),
) -> dict:
    _ensure_section_lock(section_id, locked_section_id)
    return await get_section_incoming_transfers(db, section_id=section_id)


@router.get(
    "/history",
    dependencies=[Depends(require_role(list(READER_ROLES)))],
)
async def transfer_history_generic(
    section_id: Optional[int] = Query(default=None),
    spg_id: Optional[int] = Query(default=None),
    limit: int = Query(default=50, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
    search: str | None = Query(default=None),
    status: str | None = Query(default=None),
    sort_by: str = Query(default="created_at"),
    sort_order: str = Query(default="desc"),
    date_from: datetime | None = Query(default=None),
    date_to: datetime | None = Query(default=None),
    product_sku: str | None = Query(default=None),
    from_section_name: str | None = Query(default=None),
    to_section_name: str | None = Query(default=None),
    db: AsyncSession = Depends(get_db),
    locked_section_id: int | None = Depends(get_single_window_locked_section_id),
) -> dict:
    if locked_section_id is not None and section_id is None:
        section_id = locked_section_id
    _ensure_section_lock(section_id, locked_section_id)
    return await get_section_transfer_history(
        db,
        section_id=section_id,
        spg_id=spg_id,
        limit=limit,
        offset=offset,
        search=search,
        status=status,
        sort_by=sort_by,
        sort_order=sort_order,
        date_from=date_from,
        date_to=date_to,
        product_sku=product_sku,
        from_section_name=from_section_name,
        to_section_name=to_section_name,
    )


@router.get("/{transfer_id}", dependencies=[Depends(require_role(list(READER_ROLES)))])
async def transfer_details(transfer_id: int, db: AsyncSession = Depends(get_db)) -> dict:
    try:
        return await get_transfer_details(db, transfer_id)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.put("/{transfer_id}", dependencies=[Depends(require_role(list(TRANSFER_WRITER_ROLES)))])
async def correct_transfer_qty(
    transfer_id: int,
    payload: CorrectTransferPayload,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> dict:
    try:
        return await correct_transfer(
            db,
            transfer_id=transfer_id,
            new_quantity=payload.quantity,
            actor_id=current_user.id,
            comment=payload.comment,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post("/{transfer_id}/cancel", dependencies=[Depends(require_role(list(TRANSFER_WRITER_ROLES)))])
async def cancel_transfer_qty(
    transfer_id: int,
    comment: Optional[str] = Query(default=None),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> dict:
    try:
        return await cancel_transfer(
            db,
            transfer_id=transfer_id,
            actor_id=current_user.id,
            comment=comment,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc





@router.get(
    "/sections/{section_id}/history",
    dependencies=[Depends(require_role(list(READER_ROLES)))],
)
async def transfer_history(
    section_id: int,
    limit: int = Query(default=50, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
    search: str | None = Query(default=None),
    status: str | None = Query(default=None),
    sort_by: str = Query(default="created_at"),
    sort_order: str = Query(default="desc"),
    date_from: datetime | None = Query(default=None),
    date_to: datetime | None = Query(default=None),
    product_sku: str | None = Query(default=None),
    from_section_name: str | None = Query(default=None),
    to_section_name: str | None = Query(default=None),
    db: AsyncSession = Depends(get_db),
    locked_section_id: int | None = Depends(get_single_window_locked_section_id),
) -> dict:
    _ensure_section_lock(section_id, locked_section_id)
    return await get_section_transfer_history(
        db,
        section_id=section_id,
        limit=limit,
        offset=offset,
        search=search,
        status=status,
        sort_by=sort_by,
        sort_order=sort_order,
        date_from=date_from,
        date_to=date_to,
        product_sku=product_sku,
        from_section_name=from_section_name,
        to_section_name=to_section_name,
    )



