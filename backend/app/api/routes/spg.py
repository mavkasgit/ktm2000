from datetime import datetime
from decimal import Decimal
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, status, File, UploadFile
from pydantic import BaseModel
from sqlalchemy import delete, func, select, update
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.api.deps import READER_ROLES, WRITER_ROLES, get_current_user, require_role
from app.core.database import get_db
from app.models.movement import Movement, MovementType
from app.models.product import Product
from app.models.route import ProductionRoute, RouteStage, RouteOperation, RouteRuleProfile, SectionOperation
from app.models.section import Section
from app.models.spg import SpgSection, StorageProductionGroup
from app.models.user import User
from app.models.spg_remainder import SpgRemainder
from app.models.work_task import WorkTask
from app.services.shopfloor.common import _get_user_snapshot_name
from app.services.shopfloor.queries_spg import get_spg_snapshot
from app.services.route_selection import select_route_for_payload

router = APIRouter(prefix="/spg", tags=["spg"])


# ─── Schemas ─────────────────────────────────────────────────────────────────


class SpgSectionIn(BaseModel):
    section_id: int
    sort_order: int = 0


class SpgIn(BaseModel):
    code: str
    name: str
    description: str | None = None
    sort_order: int = 0
    is_active: bool = True
    icon: str | None = None
    icon_color: str | None = None
    section_ids: list[int] = []


class SpgPatch(BaseModel):
    name: str | None = None
    description: str | None = None
    sort_order: int | None = None
    is_active: bool | None = None
    icon: str | None = None
    icon_color: str | None = None
    section_ids: list[int] | None = None


class SpgSectionOut(BaseModel):
    section_id: int
    section_code: str
    section_name: str
    sort_order: int


class SpgOut(BaseModel):
    id: int
    code: str
    name: str
    description: str | None
    sort_order: int
    is_active: bool
    icon: str | None
    icon_color: str | None
    sections: list[SpgSectionOut]


# ─── Helpers ──────────────────────────────────────────────────────────────────


async def _build_spg_out(db: AsyncSession, spg: StorageProductionGroup) -> SpgOut:
    bindings = (
        await db.execute(
            select(SpgSection)
            .where(SpgSection.spg_id == spg.id)
            .order_by(SpgSection.sort_order)
        )
    ).scalars().all()

    section_ids = [b.section_id for b in bindings]
    if section_ids:
        sections = (
            await db.execute(select(Section).where(Section.id.in_(section_ids)))
        ).scalars().all()
        sec_map = {s.id: s for s in sections}
    else:
        sec_map = {}

    sections_out = []
    for b in bindings:
        sec = sec_map.get(b.section_id)
        if sec:
            sections_out.append(SpgSectionOut(
                section_id=sec.id,
                section_code=sec.code,
                section_name=sec.name,
                sort_order=b.sort_order,
            ))

    return SpgOut(
        id=spg.id,
        code=spg.code,
        name=spg.name,
        description=spg.description,
        sort_order=spg.sort_order,
        is_active=spg.is_active,
        icon=spg.icon,
        icon_color=spg.icon_color,
        sections=sections_out,
    )


async def _sync_section_bindings(
    db: AsyncSession, spg: StorageProductionGroup, section_ids: list[int]
) -> None:
    await db.execute(delete(SpgSection).where(SpgSection.spg_id == spg.id))
    for idx, sid in enumerate(section_ids):
        db.add(SpgSection(spg_id=spg.id, section_id=sid, sort_order=idx * 10))


# ─── Endpoints ────────────────────────────────────────────────────────────────


@router.get("", response_model=list[SpgOut])
async def list_spgs(db: AsyncSession = Depends(get_db)) -> list[SpgOut]:
    items = (
        await db.execute(
            select(StorageProductionGroup).order_by(StorageProductionGroup.sort_order, StorageProductionGroup.id)
        )
    ).scalars().all()
    return [await _build_spg_out(db, item) for item in items]


@router.get("/{spg_id}", response_model=SpgOut)
async def get_spg(spg_id: int, db: AsyncSession = Depends(get_db)) -> SpgOut:
    spg = await db.get(StorageProductionGroup, spg_id)
    if spg is None:
        raise HTTPException(status_code=404, detail="SPG not found")
    return await _build_spg_out(db, spg)


@router.post("", response_model=SpgOut, status_code=status.HTTP_201_CREATED)
async def create_spg(payload: SpgIn, db: AsyncSession = Depends(get_db)) -> SpgOut:
    existing = await db.scalar(
        select(StorageProductionGroup).where(StorageProductionGroup.code == payload.code)
    )
    if existing:
        raise HTTPException(status_code=409, detail="SPG code already exists")

    spg = StorageProductionGroup(
        code=payload.code,
        name=payload.name,
        description=payload.description,
        sort_order=payload.sort_order,
        is_active=payload.is_active,
        icon=payload.icon,
        icon_color=payload.icon_color,
    )
    db.add(spg)
    await db.flush()

    if payload.section_ids:
        await _sync_section_bindings(db, spg, payload.section_ids)

    return await _build_spg_out(db, spg)


@router.patch("/{spg_id}", response_model=SpgOut)
async def patch_spg(spg_id: int, payload: SpgPatch, db: AsyncSession = Depends(get_db)) -> SpgOut:
    spg = await db.get(StorageProductionGroup, spg_id)
    if spg is None:
        raise HTTPException(status_code=404, detail="SPG not found")

    for key, value in payload.model_dump(exclude_unset=True).items():
        if key != "section_ids":
            setattr(spg, key, value)

    if payload.section_ids is not None:
        await _sync_section_bindings(db, spg, payload.section_ids)

    await db.flush()
    return await _build_spg_out(db, spg)


@router.delete("/{spg_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_spg(spg_id: int, db: AsyncSession = Depends(get_db)):
    spg = await db.get(StorageProductionGroup, spg_id)
    if spg is None:
        raise HTTPException(status_code=404, detail="SPG not found")
    await db.execute(delete(SpgSection).where(SpgSection.spg_id == spg.id))
    await db.delete(spg)
    await db.flush()


@router.get("/{spg_id}/snapshot")
async def snapshot_spg(spg_id: int, db: AsyncSession = Depends(get_db)):
    spg = await db.get(StorageProductionGroup, spg_id)
    if spg is None:
        raise HTTPException(status_code=404, detail="SPG not found")
    return await get_spg_snapshot(db, spg_id=spg_id)


@router.get("/{spg_id}/availability", dependencies=[Depends(require_role(list(READER_ROLES)))])
async def get_spg_availability(
    spg_id: int,
    product_id: int,
    section_id: int,
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Return current available quantity for a product in a section, plus the SPG's requires_lot flag.

    Used by the UI to cap the manual-operation out-quantity when requires_lot is set.
    """
    spg = await db.get(StorageProductionGroup, spg_id)
    if spg is None:
        raise HTTPException(status_code=404, detail="SPG not found")

    section_ids = (await db.execute(
        select(SpgSection.section_id).where(SpgSection.spg_id == spg_id)
    )).scalars().all()
    if section_id not in section_ids:
        raise HTTPException(status_code=400, detail="Section does not belong to this SPG")

    available = await db.scalar(
        select(func.coalesce(func.sum(SpgRemainder.remainder_quantity), 0))
        .where(
            SpgRemainder.product_id == product_id,
            SpgRemainder.spg_id == spg_id,
            SpgRemainder.consumed_at.is_(None),
        )
    )

    return {
        "spg_id": spg_id,
        "product_id": product_id,
        "section_id": section_id,
        "available": float(available or 0),
        "requires_lot": spg.requires_lot,
    }


# ─── Manual Remainders (Inventory) ───────────────────────────────────────────


class CompletedStageIn(BaseModel):
    section_id: int
    operation_code: str | None = None
    operation_name: str
    sequence: int


class ManualRemainderCreate(BaseModel):
    product_id: int
    section_id: int
    quantity: Decimal
    completed_stages: list[CompletedStageIn] = []


class ManualRemainderUpdate(BaseModel):
    quantity: Decimal | None = None
    section_id: int | None = None
    completed_stages: list[CompletedStageIn] | None = None


class RemainderOut(BaseModel):
    id: int
    product_id: int
    product_sku: str
    product_name: str
    spg_id: int
    spg_code: str
    spg_name: str
    section_id: int | None = None
    section_code: str | None = None
    section_name: str | None = None
    remainder_quantity: float
    original_issued: float
    completed_stages: list[dict]
    source: str
    created_at: str


@router.get("/{spg_id}/remainders", response_model=list[RemainderOut])
async def list_spg_remainders(spg_id: int, db: AsyncSession = Depends(get_db)) -> list[RemainderOut]:
    """List all active remainders for sections in this SPG."""
    spg = await db.get(StorageProductionGroup, spg_id)
    if spg is None:
        raise HTTPException(status_code=404, detail="SPG not found")

    rows = (await db.execute(
        select(SpgRemainder, Product.sku, Product.name, StorageProductionGroup.code, StorageProductionGroup.name)
        .join(Product, SpgRemainder.product_id == Product.id)
        .join(StorageProductionGroup, SpgRemainder.spg_id == StorageProductionGroup.id)
        .where(
            SpgRemainder.spg_id == spg_id,
            SpgRemainder.consumed_at.is_(None),
        )
        .order_by(SpgRemainder.created_at.desc())
    )).all()

    return [
        RemainderOut(
            id=r.id,
            product_id=r.product_id,
            product_sku=sku,
            product_name=name,
            spg_id=r.spg_id,
            spg_code=spg_code,
            spg_name=spg_name,
            remainder_quantity=float(r.remainder_quantity),
            original_issued=float(r.original_issued),
            completed_stages=r.completed_stages_json,
            source=r.source,
            created_at=r.created_at.isoformat(),
        )
        for r, sku, name, spg_code, spg_name in rows
    ]


@router.post("/{spg_id}/remainders", response_model=RemainderOut, status_code=status.HTTP_201_CREATED)
async def create_manual_remainder(
    spg_id: int,
    payload: ManualRemainderCreate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> RemainderOut:
    """Create a manual remainder (inventory entry) for a product in a SPG."""
    spg = await db.get(StorageProductionGroup, spg_id)
    if spg is None:
        raise HTTPException(status_code=404, detail="SPG not found")

    # Validate section belongs to this SPG
    section_ids = (await db.execute(
        select(SpgSection.section_id).where(SpgSection.spg_id == spg_id)
    )).scalars().all()
    if payload.section_id not in section_ids:
        raise HTTPException(status_code=400, detail="Section does not belong to this SPG")

    product = await db.get(Product, payload.product_id)
    if product is None:
        raise HTTPException(status_code=404, detail="Product not found")

    section = await db.get(Section, payload.section_id)
    if section is None:
        raise HTTPException(status_code=404, detail="Section not found")

    if payload.quantity <= 0:
        raise HTTPException(status_code=400, detail="Quantity must be positive")

    stages = [s.model_dump() for s in payload.completed_stages]

    actor_name = await _get_user_snapshot_name(db, current_user.id)
    remainder = SpgRemainder(
        product_id=payload.product_id,
        spg_id=spg_id,
        route_stage_id=None,
        section_plan_line_id=None,
        origin_task_id=None,
        remainder_quantity=payload.quantity,
        original_issued=payload.quantity,
        completed_stages_json=stages,
        source="manual",
        created_by=current_user.id,
        created_by_user_name=actor_name,
    )
    db.add(remainder)
    await db.flush()
    await db.refresh(remainder)

    from app.services.shopfloor.operations_tasks import trigger_auto_consume_for_spg_tasks
    await trigger_auto_consume_for_spg_tasks(db, spg_id=spg_id, product_id=payload.product_id, actor_id=current_user.id)

    return RemainderOut(
        id=remainder.id,
        product_id=product.id,
        product_sku=product.sku,
        product_name=product.name,
        spg_id=spg.id,
        spg_code=spg.code,
        spg_name=spg.name,
        section_id=section.id,
        section_code=section.code,
        section_name=section.name,
        remainder_quantity=float(remainder.remainder_quantity),
        original_issued=float(remainder.original_issued),
        completed_stages=remainder.completed_stages_json,
        source=remainder.source,
        created_at=remainder.created_at.isoformat(),
    )


@router.patch("/{spg_id}/remainders/{remainder_id}", response_model=RemainderOut)
async def update_manual_remainder(
    spg_id: int,
    remainder_id: int,
    payload: ManualRemainderUpdate,
    db: AsyncSession = Depends(get_db),
) -> RemainderOut:
    """Update a manual remainder quantity or stages."""
    remainder = await db.get(SpgRemainder, remainder_id)
    if remainder is None:
        raise HTTPException(status_code=404, detail="Remainder not found")

    if payload.quantity is not None:
        if payload.quantity <= 0:
            raise HTTPException(status_code=400, detail="Quantity must be positive")
        remainder.remainder_quantity = payload.quantity

    if payload.section_id is not None:
        section_ids = (await db.execute(
            select(SpgSection.section_id).where(SpgSection.spg_id == spg_id)
        )).scalars().all()
        if payload.section_id not in section_ids:
            raise HTTPException(status_code=400, detail="Section does not belong to this SPG")
        # In the new logic, remainder is bound to SPG. So section_id just validates belonging to the SPG.
        # But we keep it in mind. We can update spg_id if a section of a different SPG was selected.
        remainder.spg_id = spg_id

    if payload.completed_stages is not None:
        remainder.completed_stages_json = [s.model_dump() for s in payload.completed_stages]

    await db.flush()
    await db.refresh(remainder)

    product = await db.get(Product, remainder.product_id)
    spg = await db.get(StorageProductionGroup, remainder.spg_id)

    # For backward compatibility fields
    section_id = payload.section_id or (section_ids[0] if 'section_ids' in locals() and section_ids else None)
    section = await db.get(Section, section_id) if section_id else None

    return RemainderOut(
        id=remainder.id,
        product_id=product.id,
        product_sku=product.sku,
        product_name=product.name,
        spg_id=spg.id,
        spg_code=spg.code,
        spg_name=spg.name,
        section_id=section.id if section else None,
        section_code=section.code if section else None,
        section_name=section.name if section else None,
        remainder_quantity=float(remainder.remainder_quantity),
        original_issued=float(remainder.original_issued),
        completed_stages=remainder.completed_stages_json,
        source=remainder.source,
        created_at=remainder.created_at.isoformat(),
    )


@router.delete("/{spg_id}/remainders/{remainder_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_manual_remainder(spg_id: int, remainder_id: int, db: AsyncSession = Depends(get_db)):
    """Delete a manual remainder (mark as consumed)."""
    remainder = await db.get(SpgRemainder, remainder_id)
    if remainder is None:
        raise HTTPException(status_code=404, detail="Remainder not found")
    # Soft-delete: mark as consumed
    remainder.consumed_at = datetime.now()
    remainder.remainder_quantity = 0
    await db.flush()


# ─── Manual Operations (no plan task) ───────────────────────────────────────


class ManualOperationIn(BaseModel):
    product_id: int
    section_id: int
    operation_type: str  # "in" | "out"
    quantity: Decimal
    reason: str | None = None
    comment: str | None = None
    idempotency_key: str | None = None


class ManualOperationOut(BaseModel):
    movement_id: int
    remainder_id: int | None
    operation_type: str
    product_id: int
    product_sku: str
    section_id: int
    section_code: str
    quantity: float
    new_remainder_quantity: float
    idempotent_replay: bool = False


@router.post(
    "/{spg_id}/manual-operation",
    response_model=ManualOperationOut,
    dependencies=[Depends(require_role(list(WRITER_ROLES)))],
)
async def manual_stock_operation(
    spg_id: int,
    payload: ManualOperationIn,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> ManualOperationOut:
    """Perform a manual stock operation without a plan-based task.

    operation_type:
        - "in"  — приход на склад (увеличивает доступное кол-во)
        - "out" — расход со склада (уменьшает, может уходить в минус)

    Each operation is logged in `movements` and updates `warehouse_remainders`.
    """
    if payload.operation_type not in ("in", "out"):
        raise HTTPException(status_code=400, detail="operation_type must be 'in' or 'out'")

    qty = Decimal(str(payload.quantity))
    if qty <= 0:
        raise HTTPException(status_code=400, detail="quantity must be positive")

    spg = await db.get(StorageProductionGroup, spg_id)
    if spg is None:
        raise HTTPException(status_code=404, detail="SPG not found")

    if payload.operation_type == "out" and spg.requires_lot:
        # Check current available for this product+SPG
        available = await db.scalar(
            select(func.coalesce(func.sum(SpgRemainder.remainder_quantity), 0))
            .where(
                SpgRemainder.product_id == payload.product_id,
                SpgRemainder.spg_id == spg_id,
                SpgRemainder.consumed_at.is_(None),
            )
        )
        if qty > available:
            raise HTTPException(
                status_code=400,
                detail=f"SPG requires lot tracking: cannot go negative (available={available}, requested={qty})",
            )

    # Idempotency
    if payload.idempotency_key:
        existing_movement = await db.scalar(
            select(Movement).where(Movement.idempotency_key == payload.idempotency_key)
        )
        if existing_movement is not None:
            product_existing = await db.get(Product, existing_movement.product_id)
            sec_id = existing_movement.from_section_id or existing_movement.to_section_id or 0
            sec_existing = await db.get(Section, sec_id) if sec_id else None
            return ManualOperationOut(
                movement_id=existing_movement.id,
                remainder_id=None,
                operation_type=payload.operation_type,
                product_id=existing_movement.product_id,
                product_sku=product_existing.sku if product_existing else "",
                section_id=sec_id,
                section_code=sec_existing.code if sec_existing else "",
                quantity=float(existing_movement.quantity),
                new_remainder_quantity=0,
                idempotent_replay=True,
            )

    # Validate section belongs to SPG
    section_ids = (await db.execute(
        select(SpgSection.section_id).where(SpgSection.spg_id == spg_id)
    )).scalars().all()
    if payload.section_id not in section_ids:
        raise HTTPException(status_code=400, detail="Section does not belong to this SPG")

    product = await db.get(Product, payload.product_id)
    if product is None:
        raise HTTPException(status_code=404, detail="Product not found")

    section = await db.get(Section, payload.section_id)
    if section is None:
        raise HTTPException(status_code=404, detail="Section not found")

    now = datetime.now()
    actor_name = await _get_user_snapshot_name(db, current_user.id)
    affected_remainder_id: int | None = None
    new_qty: float = 0.0

    if payload.operation_type == "in":
        # Find existing active manual remainder for this product+SPG
        existing = await db.scalar(
            select(SpgRemainder)
            .where(
                SpgRemainder.product_id == payload.product_id,
                SpgRemainder.spg_id == spg_id,
                SpgRemainder.source == "manual",
                SpgRemainder.consumed_at.is_(None),
            )
            .order_by(SpgRemainder.created_at.desc())
        )
        if existing is not None:
            existing.remainder_quantity = Decimal(str(existing.remainder_quantity)) + qty
            existing.original_issued = Decimal(str(existing.original_issued)) + qty
            if existing.remainder_quantity == 0:
                existing.consumed_at = now
            affected_remainder_id = existing.id
            new_qty = float(existing.remainder_quantity)
            await db.flush()
        else:
            rem = SpgRemainder(
                product_id=payload.product_id,
                spg_id=spg_id,
                route_stage_id=None,
                section_plan_line_id=None,
                origin_task_id=None,
                remainder_quantity=qty,
                original_issued=qty,
                completed_stages_json=[],
                source="manual",
                created_by=current_user.id,
                created_by_user_name=actor_name,
            )
            db.add(rem)
            await db.flush()
            affected_remainder_id = rem.id
            new_qty = float(rem.remainder_quantity)

        from app.services.shopfloor.operations_tasks import trigger_auto_consume_for_spg_tasks
        await trigger_auto_consume_for_spg_tasks(db, spg_id=spg_id, product_id=payload.product_id, actor_id=current_user.id)
    else:  # "out"
        # Find oldest active remainder (FIFO) for this product+SPG
        existing = await db.scalar(
            select(SpgRemainder)
            .where(
                SpgRemainder.product_id == payload.product_id,
                SpgRemainder.spg_id == spg_id,
                SpgRemainder.consumed_at.is_(None),
            )
            .order_by(SpgRemainder.created_at.asc())
        )
        if existing is not None:
            existing.remainder_quantity = Decimal(str(existing.remainder_quantity)) - qty
            if existing.remainder_quantity == 0:
                existing.consumed_at = now
            affected_remainder_id = existing.id
            new_qty = float(existing.remainder_quantity)
        else:
            # No remainder — create a negative one to record the over-issue
            rem = SpgRemainder(
                product_id=payload.product_id,
                spg_id=spg_id,
                route_stage_id=None,
                section_plan_line_id=None,
                origin_task_id=None,
                remainder_quantity=-qty,
                original_issued=qty,
                completed_stages_json=[],
                source="manual",
                created_by=current_user.id,
                created_by_user_name=actor_name,
            )
            db.add(rem)
            await db.flush()
            affected_remainder_id = rem.id
            new_qty = float(rem.remainder_quantity)

    # Log movement
    movement = Movement(
        product_id=payload.product_id,
        task_id=None,
        section_plan_line_id=None,
        from_section_id=payload.section_id if payload.operation_type == "out" else None,
        to_section_id=payload.section_id if payload.operation_type == "in" else None,
        movement_type=MovementType.manual_in if payload.operation_type == "in" else MovementType.manual_out,
        quantity=qty,
        reason=payload.reason,
        comment=payload.comment,
        created_by=current_user.id,
        executor_user_id=current_user.id,
        created_by_user_name=actor_name,
        executor_user_name=actor_name,
        performed_at=now,
        accounted_at=now,
        idempotency_key=payload.idempotency_key,
    )
    db.add(movement)
    await db.flush()

    return ManualOperationOut(
        movement_id=movement.id,
        remainder_id=affected_remainder_id,
        operation_type=payload.operation_type,
        product_id=product.id,
        product_sku=product.sku,
        section_id=section.id,
        section_code=section.code,
        quantity=float(qty),
        new_remainder_quantity=new_qty,
    )


class SpgReconcileIn(BaseModel):
    product_id: int
    section_id: int
    actual_quantity: Decimal
    comment: str | None = None


class SpgReconcileOut(BaseModel):
    remainder_id: int
    product_id: int
    section_id: int
    actual_quantity: float
    adjustment_quantity: float


@router.post(
    "/{spg_id}/reconcile",
    response_model=SpgReconcileOut,
    dependencies=[Depends(require_role(list(WRITER_ROLES)))],
)
async def reconcile_stock(
    spg_id: int,
    payload: SpgReconcileIn,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> SpgReconcileOut:
    """Reconcile inventory: set exact actual quantity, expire old remainders, and log adjustment movement."""
    if payload.actual_quantity < 0:
        raise HTTPException(status_code=400, detail="actual_quantity must be non-negative")

    spg = await db.get(StorageProductionGroup, spg_id)
    if spg is None:
        raise HTTPException(status_code=404, detail="SPG not found")

    # Validate section belongs to SPG
    section_ids = (await db.execute(
        select(SpgSection.section_id).where(SpgSection.spg_id == spg_id)
    )).scalars().all()
    if payload.section_id not in section_ids:
        raise HTTPException(status_code=400, detail="Section does not belong to this SPG")

    product = await db.get(Product, payload.product_id)
    if product is None:
        raise HTTPException(status_code=404, detail="Product not found")

    section = await db.get(Section, payload.section_id)
    if section is None:
        raise HTTPException(status_code=404, detail="Section not found")

    now = datetime.now()
    actor_name = await _get_user_snapshot_name(db, current_user.id)

    # 1. Fetch active remainders
    active_remainders = (await db.execute(
        select(SpgRemainder)
        .where(
            SpgRemainder.product_id == payload.product_id,
            SpgRemainder.spg_id == spg_id,
            SpgRemainder.consumed_at.is_(None),
        )
    )).scalars().all()

    current_qty = sum((r.remainder_quantity for r in active_remainders), Decimal("0"))
    adjustment_qty = payload.actual_quantity - current_qty

    # 2. Mark old remainders as consumed/expired
    for r in active_remainders:
        r.consumed_at = now
        r.remainder_quantity = Decimal("0")

    # 3. Create one new active remainder if actual_quantity > 0
    new_remainder_id = 0
    if payload.actual_quantity > 0:
        rem = SpgRemainder(
            product_id=payload.product_id,
            spg_id=spg_id,
            route_stage_id=None,
            section_plan_line_id=None,
            origin_task_id=None,
            remainder_quantity=payload.actual_quantity,
            original_issued=payload.actual_quantity,
            completed_stages_json=[],
            source="manual",
            created_by=current_user.id,
            created_by_user_name=actor_name,
            created_at=now,
        )
        db.add(rem)
        await db.flush()
        new_remainder_id = rem.id

    # 4. Log adjustment movement if difference exists
    if abs(adjustment_qty) > 0:
        movement = Movement(
            product_id=payload.product_id,
            task_id=None,
            section_plan_line_id=None,
            from_section_id=payload.section_id if adjustment_qty < 0 else None,
            to_section_id=payload.section_id if adjustment_qty > 0 else None,
            movement_type=MovementType.adjustment,
            quantity=abs(adjustment_qty),
            reason="inventory_reconciliation",
            comment=payload.comment,
            created_by=current_user.id,
            executor_user_id=current_user.id,
            created_by_user_name=actor_name,
            executor_user_name=actor_name,
            performed_at=now,
            accounted_at=now,
        )
        db.add(movement)
        await db.flush()

    return SpgReconcileOut(
        remainder_id=new_remainder_id,
        product_id=payload.product_id,
        section_id=payload.section_id,
        actual_quantity=float(payload.actual_quantity),
        adjustment_quantity=float(adjustment_qty),
    )


# ─── History ────────────────────────────────────────────────────────────────


class RemainderHistoryOut(BaseModel):
    remainder: dict
    origin: dict | None
    route: dict | None
    consumed_by: dict | None
    completed_stages: list[dict]
    movements: list[dict]


@router.get(
    "/{spg_id}/remainders/{remainder_id}/history",
    response_model=RemainderHistoryOut,
    dependencies=[Depends(require_role(list(READER_ROLES)))],
)
async def get_remainder_history(
    spg_id: int,
    remainder_id: int,
    db: AsyncSession = Depends(get_db),
) -> RemainderHistoryOut:
    """Return full traceability chain for a single remainder."""
    remainder = await db.get(SpgRemainder, remainder_id)
    if remainder is None:
        raise HTTPException(status_code=404, detail="Remainder not found")

    product = await db.get(Product, remainder.product_id)
    spg = await db.get(StorageProductionGroup, remainder.spg_id)

    spg_section_ids = (await db.execute(
        select(SpgSection.section_id).where(SpgSection.spg_id == remainder.spg_id)
    )).scalars().all()
    section = await db.get(Section, spg_section_ids[0]) if spg_section_ids else None

    remainder_payload = {
        "id": remainder.id,
        "product_id": remainder.product_id,
        "product_sku": product.sku if product else "",
        "product_name": product.name if product else "",
        "spg_id": remainder.spg_id,
        "spg_code": spg.code if spg else "",
        "spg_name": spg.name if spg else "",
        "section_id": section.id if section else None,
        "section_code": section.code if section else "",
        "section_name": section.name if section else "",
        "remainder_quantity": float(remainder.remainder_quantity),
        "original_issued": float(remainder.original_issued),
        "source": remainder.source,
        "completed_stages": remainder.completed_stages_json,
        "created_by": remainder.created_by,
        "created_by_user_name": remainder.created_by_user_name,
        "created_at": remainder.created_at.isoformat(),
        "consumed_at": remainder.consumed_at.isoformat() if remainder.consumed_at else None,
    }

    # ── Origin (task that created this remainder) ──────────────────────────
    origin_payload: dict | None = None
    route_payload: dict | None = None

    if remainder.origin_task_id is not None:
        task = await db.get(WorkTask, remainder.origin_task_id)
        if task is not None:
            stage = await db.get(RouteStage, task.route_stage_id)
            op_code = stage.operations[0].operation_code if stage and stage.operations else None
            op_name = ", ".join(op.operation_name for op in stage.operations) if stage and stage.operations else ""
            origin_payload = {
                "task_id": task.id,
                "task_status": task.status.value,
                "planned_quantity": float(task.planned_quantity),
                "issued_quantity": float(task.cached_issued_quantity),
                "completed_quantity": float(task.cached_completed_quantity),
                "in_work_quantity": float(task.cached_in_work_quantity),
                "transferred_quantity": float(task.cached_transferred_quantity),
                "section_id": task.section_id,
                "operation_code": op_code,
                "operation_name": op_name,
                "sequence": stage.sequence if stage else None,
                "created_at": task.created_at.isoformat(),
            }

            # Resolve full route via plan line
            if remainder.section_plan_line_id is not None:
                from app.models.internal_plan import InternalPlan, SectionPlanLine
                line = await db.get(SectionPlanLine, remainder.section_plan_line_id)
                if line is not None:
                    route = await db.get(ProductionRoute, line.route_id)
                    if route is not None:
                        stages_rows = (await db.execute(
                            select(RouteStage)
                            .where(RouteStage.route_id == route.id)
                            .order_by(RouteStage.sequence)
                        )).scalars().all()
                        steps_out = []
                        for s in stages_rows:
                            sec = await db.get(Section, s.section_id)
                            sop_code = s.operations[0].operation_code if s.operations else None
                            sop_name = ", ".join(op.operation_name for op in s.operations) if s.operations else ""
                            steps_out.append({
                                "sequence": s.sequence,
                                "section_id": s.section_id,
                                "section_code": sec.code if sec else "",
                                "section_name": sec.name if sec else "",
                                "operation_code": sop_code,
                                "operation_name": sop_name,
                                "is_significant": s.is_significant,
                                "is_final": s.is_final,
                            })
                        route_payload = {
                            "route_id": route.id,
                            "route_name": route.name,
                            "route_code": route.code,
                            "current_sequence": line.sequence,
                            "steps": steps_out,
                        }

    # ── Consumed by ────────────────────────────────────────────────────────
    consumed_by_payload: dict | None = None
    if remainder.consumed_by_task_id is not None:
        task = await db.get(WorkTask, remainder.consumed_by_task_id)
        if task is not None:
            stage = await db.get(RouteStage, task.route_stage_id)
            op_code = stage.operations[0].operation_code if stage and stage.operations else None
            op_name = ", ".join(op.operation_name for op in stage.operations) if stage and stage.operations else ""
            consumed_by_payload = {
                "task_id": task.id,
                "task_status": task.status.value,
                "section_id": task.section_id,
                "operation_code": op_code,
                "operation_name": op_name,
                "sequence": stage.sequence if stage else None,
            }

    # ── Movements log (all movements touching this product in this SPG) ──
    movements_out = []
    if spg_section_ids:
        movements_rows = (await db.execute(
            select(Movement)
            .where(
                Movement.product_id == remainder.product_id,
                (Movement.from_section_id.in_(spg_section_ids)) | (Movement.to_section_id.in_(spg_section_ids)),
            )
            .order_by(Movement.created_at.desc())
            .limit(200)
        )).scalars().all()

        for m in movements_rows:
            movements_out.append({
                "id": m.id,
                "movement_type": m.movement_type.value,
                "quantity": float(m.quantity),
                "task_id": m.task_id,
                "from_section_id": m.from_section_id,
                "to_section_id": m.to_section_id,
                "reason": m.reason,
                "comment": m.comment,
                "created_by": m.created_by,
                "created_by_user_name": m.created_by_user_name,
                "executor_user_id": m.executor_user_id,
                "executor_user_name": m.executor_user_name,
                "created_at": m.created_at.isoformat(),
                "performed_at": m.performed_at.isoformat() if m.performed_at else None,
            })

    return RemainderHistoryOut(
        remainder=remainder_payload,
        origin=origin_payload,
        route=route_payload,
        consumed_by=consumed_by_payload,
        completed_stages=remainder.completed_stages_json,
        movements=movements_out,
    )


def _decimal_or_none(value: Any) -> Decimal | None:
    if value is None or value == "":
        return None
    try:
        if isinstance(value, Decimal):
            return value
        if isinstance(value, int):
            return Decimal(value)
        if isinstance(value, float):
            return Decimal(str(value))
        normalized = str(value).replace(" ", "").replace(",", ".").strip()
        if not normalized:
            return None
        return Decimal(normalized)
    except Exception:
        return None


async def _resolve_completed_stages_for_product_excel(
    db: AsyncSession,
    product: Product,
    completed_ops_str: str,
) -> list[dict]:
    # 1. Fetch route stages for this product (same logic as GET /products/{product_id}/route-stages)
    profiles = (
        await db.execute(
            select(RouteRuleProfile)
            .where(RouteRuleProfile.is_active == True)
            .order_by(RouteRuleProfile.priority.desc(), RouteRuleProfile.id.asc())
        )
    ).scalars().all()

    matched_route = None
    for profile in profiles:
        selection = await select_route_for_payload(db, {}, product, profile_id=profile.id)
        if selection.route is not None:
            matched_route = selection.route
            break

    if not matched_route:
        selection = await select_route_for_payload(db, {}, product)
        if selection.route is not None:
            matched_route = selection.route

    if not matched_route:
        if product.profile_type:
            matched_route = await db.scalar(
                select(ProductionRoute)
                .where(ProductionRoute.is_active == True)
                .where(ProductionRoute.name.ilike(f"%{product.profile_type}%"))
                .limit(1)
            )
        if not matched_route and product.type:
            matched_route = await db.scalar(
                select(ProductionRoute)
                .where(ProductionRoute.is_active == True)
                .where(ProductionRoute.name.ilike(f"%{product.type}%"))
                .limit(1)
            )
        if not matched_route:
            matched_route = await db.scalar(
                select(ProductionRoute)
                .where(ProductionRoute.is_active == True)
                .order_by(ProductionRoute.sort_order, ProductionRoute.id)
                .limit(1)
            )

    if not matched_route:
        return []

    # Load stages
    stages = (
        await db.execute(
            select(RouteStage)
            .where(RouteStage.route_id == matched_route.id)
            .order_by(RouteStage.sequence)
            .options(selectinload(RouteStage.operations))
        )
    ).scalars().all()

    section_ids = {stage.section_id for stage in stages}
    sections_dict = {}
    if section_ids:
        sec_rows = (await db.execute(select(Section).where(Section.id.in_(section_ids)))).scalars().all()
        sections_dict = {s.id: s for s in sec_rows}

    # Load section operations
    section_ops_dict = {}
    if section_ids:
        ops_rows = (
            await db.execute(
                select(SectionOperation)
                .where(SectionOperation.section_id.in_(section_ids))
                .where(SectionOperation.group_code.isnot(None))
                .order_by(SectionOperation.section_id, SectionOperation.sort_order, SectionOperation.operation_code)
            )
        ).scalars().all()
        for op in ops_rows:
            section_ops_dict.setdefault(op.section_id, []).append(op)

    # 2. Parse completed operations
    tokens = [t.strip().lower() for t in completed_ops_str.split(",") if t.strip()]

    completed = []
    for token in tokens:
        found = False
        for stage in stages:
            section = sections_dict.get(stage.section_id)
            if not section:
                continue

            if any(c["section_id"] == stage.section_id for c in completed):
                continue

            has_specific_ops = any(op.operation_code is not None for op in stage.operations)
            ops_list = []
            if has_specific_ops:
                ops_list = [op for op in stage.operations if op.operation_code is not None]
            else:
                ops_list = section_ops_dict.get(stage.section_id) or []

            for op in ops_list:
                op_name_lower = op.operation_name.lower()
                op_code_lower = op.operation_code.lower() if op.operation_code else ""
                
                if token in op_name_lower or (op_code_lower and token in op_code_lower) or token in section.name.lower() or token in section.code.lower():
                    completed.append({
                        "section_id": stage.section_id,
                        "operation_code": op.operation_code,
                        "operation_name": op.operation_name,
                        "sequence": stage.sequence,
                    })
                    found = True
                    break
            if found:
                break
    return sorted(completed, key=lambda x: x["sequence"])


@router.get("/{spg_id}/defects", dependencies=[Depends(require_role(list(READER_ROLES)))])
async def get_spg_defects(
    spg_id: int,
    db: AsyncSession = Depends(get_db),
) -> list[dict]:
    # Get all sections associated with this SPG
    section_ids = (await db.execute(
        select(SpgSection.section_id).where(SpgSection.spg_id == spg_id)
    )).scalars().all()

    if not section_ids:
        return []

    # Get all defects for these sections
    from app.models.defect import Defect, DefectItem, DefectDecision
    from app.models.product import Product
    from app.models.section import Section
    from app.models.user import User

    stmt = (
        select(Defect)
        .where(Defect.section_id.in_(section_ids))
        .order_by(Defect.created_at.desc())
    )
    defects = (await db.execute(stmt)).scalars().all()

    if not defects:
        return []

    defect_ids = [d.id for d in defects]

    # Load all items for these defects
    items_rows = (await db.execute(
        select(DefectItem).where(DefectItem.defect_id.in_(defect_ids))
    )).scalars().all()
    items_by_defect = {}
    for item in items_rows:
        items_by_defect.setdefault(item.defect_id, []).append(item)

    # Load all decisions for these defects
    decisions_rows = (await db.execute(
        select(DefectDecision).where(DefectDecision.defect_id.in_(defect_ids))
    )).scalars().all()
    decisions_by_defect = {}
    for dec in decisions_rows:
        decisions_by_defect.setdefault(dec.defect_id, []).append(dec)

    # Fetch product, section, user, route_stage maps in bulk
    prod_ids = {d.product_id for d in defects}
    products_map = {}
    if prod_ids:
        prod_rows = (await db.execute(select(Product).where(Product.id.in_(prod_ids)))).scalars().all()
        products_map = {p.id: p for p in prod_rows}

    sect_ids = {d.section_id for d in defects} | {d.responsible_section_id for d in defects if d.responsible_section_id}
    sections_map = {}
    if sect_ids:
        sect_rows = (await db.execute(select(Section).where(Section.id.in_(sect_ids)))).scalars().all()
        sections_map = {s.id: s for s in sect_rows}

    user_ids = {d.created_by for d in defects}
    users_map = {}
    if user_ids:
        user_rows = (await db.execute(select(User).where(User.id.in_(user_ids)))).scalars().all()
        users_map = {u.id: u for u in user_rows}

    stage_ids = {d.route_stage_id for d in defects if d.route_stage_id}
    stages_map = {}
    if stage_ids:
        stage_rows = (await db.execute(
            select(RouteStage)
            .where(RouteStage.id.in_(stage_ids))
            .options(selectinload(RouteStage.operations))
        )).scalars().all()
        stages_map = {s.id: s for s in stage_rows}

    result = []
    for d in defects:
        product = products_map.get(d.product_id)
        section = sections_map.get(d.section_id)
        resp_section = sections_map.get(d.responsible_section_id) if d.responsible_section_id else None
        creator = users_map.get(d.created_by)
        stage = stages_map.get(d.route_stage_id) if d.route_stage_id else None

        d_items = items_by_defect.get(d.id, [])
        d_decisions = decisions_by_defect.get(d.id, [])

        total_quantity = sum(item.quantity for item in d_items)
        reasons_list = [item.defect_type_name_snapshot or item.reason_code for item in d_items if item.defect_type_name_snapshot or item.reason_code]
        reason_str = ", ".join(reasons_list) if reasons_list else d.comment

        stage_payload = None
        if stage:
            op_code = stage.operations[0].operation_code if stage.operations else None
            op_name = ", ".join(op.operation_name for op in stage.operations) if stage.operations else ""
            stage_payload = {
                "id": stage.id,
                "sequence": stage.sequence,
                "operation_code": op_code,
                "operation_name": op_name,
            }

        result.append({
            "id": d.id,
            "status": d.status.value,
            "product_id": d.product_id,
            "product_sku": product.sku if product else "",
            "product_name": product.name if product else "",
            "section_id": d.section_id,
            "section_code": section.code if section else "",
            "section_name": section.name if section else "",
            "task_id": d.task_id,
            "route_stage_id": d.route_stage_id,
            "route_stage": stage_payload,
            "spg_remainder_id": d.spg_remainder_id,
            "responsible_section_id": d.responsible_section_id,
            "responsible_section_code": resp_section.code if resp_section else None,
            "responsible_section_name": resp_section.name if resp_section else None,
            "comment": d.comment,
            "created_by": d.created_by,
            "created_by_user_name": creator.full_name or creator.username if creator else None,
            "created_at": d.created_at.isoformat(),
            "total_quantity": float(total_quantity),
            "reason": reason_str,
            "items": [
                {
                    "id": item.id,
                    "quantity": float(item.quantity),
                    "defect_type_code_snapshot": item.defect_type_code_snapshot,
                    "defect_type_name_snapshot": item.defect_type_name_snapshot,
                    "description": item.description,
                }
                for item in d_items
            ],
            "decisions": [
                {
                    "id": dec.id,
                    "decision_type": dec.decision_type.value,
                    "quantity": float(dec.quantity),
                    "reason": dec.reason,
                    "comment": dec.comment,
                    "decided_at": dec.decided_at.isoformat(),
                }
                for dec in d_decisions
            ],
        })

    return result


@router.post("/{spg_id}/remainders/import", dependencies=[Depends(require_role(list(WRITER_ROLES)))])
async def import_remainders_excel(
    spg_id: int,
    file: UploadFile = File(...),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> dict:
    from python_calamine import load_workbook
    from io import BytesIO

    content = await file.read()
    try:
        workbook = load_workbook(BytesIO(content))
    except Exception as exc:
        raise HTTPException(status_code=400, detail=f"Invalid Excel file: {exc}")

    # Use first sheet
    sheet = workbook.get_sheet_by_index(0)
    rows = list(sheet.iter_rows())
    if not rows:
        raise HTTPException(status_code=400, detail="Excel sheet is empty")

    # Find headers
    headers = [str(cell).strip().lower() for cell in rows[0]]
    sku_idx = -1
    qty_idx = -1
    ops_idx = -1

    for idx, h in enumerate(headers):
        if h in ("sku", "артикул", "код", "продукт", "sku/артикул", "артикул / sku"):
            sku_idx = idx
        elif h in ("quantity", "количество", "кол-во", "кол-во, шт", "кол-во шт"):
            qty_idx = idx
        elif h in ("operations", "operations_completed", "completed_stages", "операции", "стадии", "выполненные стадии", "выполненные операции"):
            ops_idx = idx

    # Fallback search if not found in first row
    if sku_idx == -1 or qty_idx == -1:
        for r_idx, r in enumerate(rows[:10]):
            r_headers = [str(cell).strip().lower() for cell in r]
            for idx, h in enumerate(r_headers):
                if h in ("sku", "артикул", "код", "продукт", "sku/артикул", "артикул / sku"):
                    sku_idx = idx
                elif h in ("quantity", "количество", "кол-во", "кол-во, шт", "кол-во шт"):
                    qty_idx = idx
                elif h in ("operations", "operations_completed", "completed_stages", "операции", "стадии", "выполненные стадии", "выполненные операции"):
                    ops_idx = idx
            if sku_idx != -1 and qty_idx != -1:
                rows = rows[r_idx:]
                break

    if sku_idx == -1:
        sku_idx = 0
    if qty_idx == -1:
        qty_idx = 1

    actor_name = await _get_user_snapshot_name(db, current_user.id)
    imported_count = 0
    errors = []
    
    data_rows = rows[1:]
    for r_idx, row in enumerate(data_rows, start=2):
        if len(row) <= max(sku_idx, qty_idx):
            continue
        
        sku_val = str(row[sku_idx]).strip()
        if not sku_val or sku_val == "None":
            continue

        qty_val = row[qty_idx]
        qty_dec = _decimal_or_none(qty_val)
        if qty_dec is None or qty_dec <= 0:
            errors.append(f"Строка {r_idx}: Неверное количество '{qty_val}'")
            continue

        product = await db.scalar(select(Product).where(Product.sku == sku_val))
        if not product:
            errors.append(f"Строка {r_idx}: Продукт с SKU '{sku_val}' не найден")
            continue

        completed_stages = []
        if ops_idx != -1 and ops_idx < len(row):
            ops_val = str(row[ops_idx]).strip()
            if ops_val and ops_val != "None":
                completed_stages = await _resolve_completed_stages_for_product_excel(db, product, ops_val)

        remainder = SpgRemainder(
            product_id=product.id,
            spg_id=spg_id,
            route_stage_id=None,
            section_plan_line_id=None,
            origin_task_id=None,
            remainder_quantity=qty_dec,
            original_issued=qty_dec,
            completed_stages_json=completed_stages,
            source="manual",
            created_by=current_user.id,
            created_by_user_name=actor_name,
        )
        db.add(remainder)
        imported_count += 1

    await db.flush()

    return {
        "success": True,
        "imported_count": imported_count,
        "errors": errors,
    }


@router.post("/{spg_id}/defects/import", dependencies=[Depends(require_role(list(WRITER_ROLES)))])
async def import_defects_excel(
    spg_id: int,
    file: UploadFile = File(...),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> dict:
    from python_calamine import load_workbook
    from io import BytesIO
    from app.models.defect import Defect, DefectItem, DefectType, DefectStatus

    content = await file.read()
    try:
        workbook = load_workbook(BytesIO(content))
    except Exception as exc:
        raise HTTPException(status_code=400, detail=f"Invalid Excel file: {exc}")

    sheet = workbook.get_sheet_by_index(0)
    rows = list(sheet.iter_rows())
    if not rows:
        raise HTTPException(status_code=400, detail="Excel sheet is empty")

    # Get all sections associated with this SPG
    section_ids = (await db.execute(
        select(SpgSection.section_id).where(SpgSection.spg_id == spg_id)
    )).scalars().all()
    if not section_ids:
        raise HTTPException(status_code=400, detail="No sections associated with this SPG")

    # Find headers
    headers = [str(cell).strip().lower() for cell in rows[0]]
    sku_idx = -1
    qty_idx = -1
    sec_idx = -1
    type_idx = -1
    cmt_idx = -1

    for idx, h in enumerate(headers):
        if h in ("sku", "артикул", "код", "продукт", "sku/артикул", "артикул / sku"):
            sku_idx = idx
        elif h in ("quantity", "количество", "кол-во", "кол-во, шт", "кол-во шт"):
            qty_idx = idx
        elif h in ("section", "участок", "код участка", "название участка"):
            sec_idx = idx
        elif h in ("defect_type", "тип брака", "тип дефекта", "код дефекта"):
            type_idx = idx
        elif h in ("comment", "комментарий", "примечание"):
            cmt_idx = idx

    # Fallback search if not found in first row
    if sku_idx == -1 or qty_idx == -1 or sec_idx == -1:
        for r_idx, r in enumerate(rows[:10]):
            r_headers = [str(cell).strip().lower() for cell in r]
            for idx, h in enumerate(r_headers):
                if h in ("sku", "артикул", "код", "продукт", "sku/артикул", "артикул / sku"):
                    sku_idx = idx
                elif h in ("quantity", "количество", "кол-во", "кол-во, шт", "кол-во шт"):
                    qty_idx = idx
                elif h in ("section", "участок", "код участка", "название участка"):
                    sec_idx = idx
                elif h in ("defect_type", "тип брака", "тип дефекта", "код дефекта"):
                    type_idx = idx
                elif h in ("comment", "комментарий", "примечание"):
                    cmt_idx = idx
            if sku_idx != -1 and qty_idx != -1 and sec_idx != -1:
                rows = rows[r_idx:]
                break

    if sku_idx == -1:
        sku_idx = 0
    if qty_idx == -1:
        qty_idx = 1
    if sec_idx == -1:
        sec_idx = 2

    imported_count = 0
    errors = []

    # Cache sections
    sections_list = (await db.execute(
        select(Section).where(Section.id.in_(section_ids))
    )).scalars().all()

    data_rows = rows[1:]
    for r_idx, row in enumerate(data_rows, start=2):
        if len(row) <= max(sku_idx, qty_idx, sec_idx):
            continue

        sku_val = str(row[sku_idx]).strip()
        if not sku_val or sku_val == "None":
            continue

        qty_val = row[qty_idx]
        qty_dec = _decimal_or_none(qty_val)
        if qty_dec is None or qty_dec <= 0:
            errors.append(f"Строка {r_idx}: Неверное количество '{qty_val}'")
            continue

        sec_val = str(row[sec_idx]).strip().lower()
        if not sec_val or sec_val == "None":
            errors.append(f"Строка {r_idx}: Не указан участок")
            continue

        # Find section among linked sections
        target_section = None
        for s in sections_list:
            if s.code.lower() == sec_val or s.name.lower() == sec_val:
                target_section = s
                break

        if not target_section:
            # Check if it exists globally to give a better error message
            global_section = await db.scalar(
                select(Section).where((Section.code.ilike(sec_val)) | (Section.name.ilike(sec_val)))
            )
            if global_section:
                errors.append(f"Строка {r_idx}: Участок '{row[sec_idx]}' не привязан к данной ГХП")
            else:
                errors.append(f"Строка {r_idx}: Участок '{row[sec_idx]}' не найден в системе")
            continue

        product = await db.scalar(select(Product).where(Product.sku == sku_val))
        if not product:
            errors.append(f"Строка {r_idx}: Продукт с SKU '{sku_val}' не найден")
            continue

        # Defect Type resolution
        defect_type = None
        defect_type_code = None
        defect_type_name = None
        if type_idx != -1 and type_idx < len(row):
            type_val = str(row[type_idx]).strip()
            if type_val and type_val != "None":
                defect_type = await db.scalar(
                    select(DefectType).where(
                        (DefectType.code.ilike(type_val)) | (DefectType.name.ilike(type_val))
                    )
                )
                if defect_type:
                    defect_type_code = defect_type.code
                    defect_type_name = defect_type.name
                else:
                    defect_type_name = type_val

        cmt_val = None
        if cmt_idx != -1 and cmt_idx < len(row):
            val = str(row[cmt_idx]).strip()
            if val and val != "None":
                cmt_val = val

        # Create Defect and DefectItem
        defect = Defect(
            product_id=product.id,
            section_id=target_section.id,
            status=DefectStatus.open,
            comment=cmt_val,
            created_by=current_user.id,
        )
        db.add(defect)
        await db.flush()

        defect_item = DefectItem(
            defect_id=defect.id,
            defect_type_id=defect_type.id if defect_type else None,
            defect_type_code_snapshot=defect_type_code,
            defect_type_name_snapshot=defect_type_name,
            quantity=qty_dec,
            created_by=current_user.id,
        )
        db.add(defect_item)
        imported_count += 1

    await db.flush()

    return {
        "success": True,
        "imported_count": imported_count,
        "errors": errors,
    }

