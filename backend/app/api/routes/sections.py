from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel
from sqlalchemy import select, delete
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.models.route import ProductionRoute, RouteStage, SectionOperation
from app.models.section import Section
from app.models.spg import SpgSection, StorageProductionGroup

router = APIRouter(prefix="/sections", tags=["sections"])


class SectionBase(BaseModel):
    code: str
    name: str
    description: str | None = None
    sort_order: int = 0
    is_active: bool = True
    kind: str = "production"
    icon: str | None = None
    icon_color: str | None = None


class SectionIn(SectionBase):
    spg_id: int


class SectionPatch(BaseModel):
    name: str | None = None
    description: str | None = None
    sort_order: int | None = None
    is_active: bool | None = None
    kind: str | None = None
    icon: str | None = None
    icon_color: str | None = None
    spg_id: int | None = None


class SpgBriefOut(BaseModel):
    id: int
    code: str
    name: str


class SectionOut(SectionBase):
    id: int
    spg_id: int | None = None
    spg_links: list[SpgBriefOut] = []
    operations_count: int = 0




@router.get("", response_model=list[SectionOut])
async def list_sections(db: AsyncSession = Depends(get_db)) -> list[SectionOut]:
    items = (await db.execute(select(Section).order_by(Section.sort_order, Section.id))).scalars().all()
    return [SectionOut.model_validate(i, from_attributes=True) for i in items]


@router.get("/{section_id}", response_model=SectionOut)
async def get_section(section_id: int, db: AsyncSession = Depends(get_db)) -> SectionOut:
    item = await db.get(Section, section_id)
    if item is None:
        raise HTTPException(status_code=404, detail="Section not found")
    return SectionOut.model_validate(item, from_attributes=True)


@router.post("", response_model=SectionOut, status_code=status.HTTP_201_CREATED)
async def create_section(payload: SectionIn, db: AsyncSession = Depends(get_db)) -> SectionOut:
    existing = await db.scalar(select(Section).where(Section.code == payload.code))
    if existing:
        raise HTTPException(status_code=409, detail="Section code already exists")
    
    spg_id = payload.spg_id
    data = payload.model_dump(exclude={"spg_id"})
    
    existing_spg = await db.get(StorageProductionGroup, spg_id)
    if existing_spg is None:
        raise HTTPException(status_code=400, detail="SPG ID does not exist")

    item = Section(**data)
    db.add(item)
    await db.flush()

    db.add(SpgSection(spg_id=spg_id, section_id=item.id, sort_order=0))
    await db.flush()

    await db.refresh(item)
    return SectionOut.model_validate(item, from_attributes=True)


@router.patch("/{section_id}", response_model=SectionOut)
async def patch_section(section_id: int, payload: SectionPatch, db: AsyncSession = Depends(get_db)) -> SectionOut:
    item = await db.get(Section, section_id)
    if item is None:
        raise HTTPException(status_code=404, detail="Section not found")
    
    data = payload.model_dump(exclude_unset=True)
    spg_id = data.pop("spg_id", None)

    if spg_id is not None:
        existing_spg = await db.get(StorageProductionGroup, spg_id)
        if existing_spg is None:
            raise HTTPException(status_code=400, detail="SPG ID does not exist")

    for key, value in data.items():
        setattr(item, key, value)

    if spg_id is not None:
        await db.execute(delete(SpgSection).where(SpgSection.section_id == section_id))
        db.add(SpgSection(spg_id=spg_id, section_id=section_id, sort_order=0))

    await db.flush()
    await db.refresh(item)
    return SectionOut.model_validate(item, from_attributes=True)


class ReorderSectionsIn(BaseModel):
    ids: list[int]


@router.post("/reorder", status_code=status.HTTP_204_NO_CONTENT)
async def reorder_sections(payload: ReorderSectionsIn, db: AsyncSession = Depends(get_db)):
    items = (await db.execute(select(Section).where(Section.id.in_(payload.ids)).order_by(Section.id))).scalars().all()
    by_id = {item.id: item for item in items}
    for idx, section_id in enumerate(payload.ids):
        section = by_id.get(section_id)
        if section:
            section.sort_order = idx * 10
    await db.flush()


@router.delete("/{section_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_section(section_id: int, db: AsyncSession = Depends(get_db)):
    item = await db.get(Section, section_id)
    if item is None:
        raise HTTPException(status_code=404, detail="Section not found")
    # Check if any route stages reference this section
    stages = (await db.execute(select(RouteStage).where(RouteStage.section_id == section_id))).scalars().all()
    if stages:
        route_ids = list({s.route_id for s in stages})
        routes = (await db.execute(select(ProductionRoute).where(ProductionRoute.id.in_(route_ids)))).scalars().all()
        route_names = ", ".join(f"«{r.name}»" for r in routes)
        raise HTTPException(status_code=409, detail=f"Нельзя удалить: участок используется в маршрутах {route_names}")
    # Cascade delete: operations first (via ORM relationship cascade)
    ops = (await db.execute(select(SectionOperation).where(SectionOperation.section_id == section_id))).scalars().all()
    for op in ops:
        await db.delete(op)
    await db.delete(item)
    await db.flush()


# ─── Operation Groups CRUD ────────────────────────────────────────────────────


class OperationGroupOut(BaseModel):
    group_code: str | None
    group_name: str | None
    sort_order: int
    operations: list[dict]


class OperationGroupCreate(BaseModel):
    group_code: str
    group_name: str
    sort_order: int = 0


class OperationGroupUpdate(BaseModel):
    group_name: str | None = None
    sort_order: int | None = None


class OperationMoveRequest(BaseModel):
    operation_id: int
    new_group_code: str


@router.get("/{section_id}/operation-groups", response_model=list[OperationGroupOut])
async def list_section_operation_groups(section_id: int, db: AsyncSession = Depends(get_db)) -> list[OperationGroupOut]:
    """List all operation groups for a section, with operations in each group."""
    section = await db.get(Section, section_id)
    if section is None:
        raise HTTPException(status_code=404, detail="Section not found")

    ops = (await db.execute(
        select(SectionOperation)
        .where(SectionOperation.section_id == section_id)
        .order_by(SectionOperation.sort_order, SectionOperation.group_code, SectionOperation.operation_code)
    )).scalars().all()

    # Group by group_code
    groups: dict[str | None, dict] = {}
    for op in ops:
        gc = op.group_code
        if gc not in groups:
            groups[gc] = {
                "group_code": gc,
                "group_name": op.group_name,
                "sort_order": op.sort_order,
                "operations": [],
            }
        groups[gc]["operations"].append({
            "id": op.id,
            "operation_code": op.operation_code,
            "operation_name": op.operation_name,
            "is_significant": op.is_significant,
            "icon": op.icon,
            "icon_color": op.icon_color,
            "group_code": op.group_code,
            "group_name": op.group_name,
            "sort_order": op.sort_order,
            "resolver_type": op.resolver_type,
        })

    return [OperationGroupOut.model_validate(g) for g in sorted(groups.values(), key=lambda g: g["sort_order"])]


@router.post("/{section_id}/operation-groups", response_model=OperationGroupOut, status_code=status.HTTP_201_CREATED)
async def create_operation_group(
    section_id: int,
    payload: OperationGroupCreate,
    db: AsyncSession = Depends(get_db),
) -> OperationGroupOut:
    """Create a new operation group by updating group_code and group_name on all section operations.

    Actually, a group is just a unique group_code value. Creating a "group" means
    we need to have at least one operation with that group_code.
    This endpoint creates a placeholder operation for the group.
    """
    section = await db.get(Section, section_id)
    if section is None:
        raise HTTPException(status_code=404, detail="Section not found")

    # Check if group_code already exists for this section
    existing = await db.scalar(
        select(SectionOperation).where(
            SectionOperation.section_id == section_id,
            SectionOperation.group_code == payload.group_code,
        ).limit(1)
    )
    if existing:
        raise HTTPException(status_code=409, detail="Group code already exists for this section")

    # Create a placeholder operation for the group
    op = SectionOperation(
        section_id=section_id,
        operation_code=f"__{payload.group_code}__",
        operation_name=payload.group_name,
        is_significant=False,
        group_code=payload.group_code,
        group_name=payload.group_name,
        sort_order=payload.sort_order,
    )
    db.add(op)
    await db.flush()
    await db.refresh(op)

    return OperationGroupOut(
        group_code=op.group_code,
        group_name=op.group_name,
        sort_order=op.sort_order,
        operations=[{
            "id": op.id,
            "operation_code": op.operation_code,
            "operation_name": op.operation_name,
            "is_significant": op.is_significant,
            "icon": op.icon,
            "icon_color": op.icon_color,
            "group_code": op.group_code,
            "group_name": op.group_name,
            "sort_order": op.sort_order,
            "resolver_type": op.resolver_type,
        }],
    )


@router.put("/{section_id}/operation-groups/{group_code}", response_model=OperationGroupOut)
async def update_operation_group(
    section_id: int,
    group_code: str,
    payload: OperationGroupUpdate,
    db: AsyncSession = Depends(get_db),
) -> OperationGroupOut:
    """Update group_name and/or sort_order for all operations in a group."""
    section = await db.get(Section, section_id)
    if section is None:
        raise HTTPException(status_code=404, detail="Section not found")

    ops = (await db.execute(
        select(SectionOperation).where(
            SectionOperation.section_id == section_id,
            SectionOperation.group_code == group_code,
        )
    )).scalars().all()

    if not ops:
        raise HTTPException(status_code=404, detail="Operation group not found")

    for op in ops:
        if payload.group_name is not None:
            op.group_name = payload.group_name
        if payload.sort_order is not None:
            op.sort_order = payload.sort_order

    await db.flush()
    await db.refresh(ops[0])

    return OperationGroupOut(
        group_code=ops[0].group_code,
        group_name=ops[0].group_name,
        sort_order=ops[0].sort_order,
        operations=[{
            "id": op.id,
            "operation_code": op.operation_code,
            "operation_name": op.operation_name,
            "is_significant": op.is_significant,
            "icon": op.icon,
            "icon_color": op.icon_color,
            "group_code": op.group_code,
            "group_name": op.group_name,
            "sort_order": op.sort_order,
            "resolver_type": op.resolver_type,
        } for op in ops],
    )


@router.delete("/{section_id}/operation-groups/{group_code}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_operation_group(
    section_id: int,
    group_code: str,
    db: AsyncSession = Depends(get_db),
):
    """Delete all operations in a group."""
    section = await db.get(Section, section_id)
    if section is None:
        raise HTTPException(status_code=404, detail="Section not found")

    ops = (await db.execute(
        select(SectionOperation).where(
            SectionOperation.section_id == section_id,
            SectionOperation.group_code == group_code,
        )
    )).scalars().all()

    if not ops:
        raise HTTPException(status_code=404, detail="Operation group not found")

    for op in ops:
        await db.delete(op)

    await db.flush()


@router.put("/{section_id}/operations/{operation_id}/move", status_code=status.HTTP_204_NO_CONTENT)
async def move_operation_to_group(
    section_id: int,
    operation_id: int,
    payload: OperationMoveRequest,
    db: AsyncSession = Depends(get_db),
):
    """Move an operation to a different group."""
    section = await db.get(Section, section_id)
    if section is None:
        raise HTTPException(status_code=404, detail="Section not found")

    op = await db.get(SectionOperation, operation_id)
    if op is None or op.section_id != section_id:
        raise HTTPException(status_code=404, detail="Operation not found in this section")

    # Check if target group exists (has at least one operation)
    target_group = await db.scalar(
        select(SectionOperation).where(
            SectionOperation.section_id == section_id,
            SectionOperation.group_code == payload.new_group_code,
        ).limit(1)
    )
    if not target_group:
        raise HTTPException(status_code=400, detail="Target group does not exist")

    op.group_code = payload.new_group_code
    op.group_name = target_group.group_name

    await db.flush()


class SectionOperationOut(BaseModel):
    id: int
    operation_code: str | None
    operation_name: str
    is_significant: bool
    group_code: str | None = None
    group_name: str | None = None


class SectionWithOperationsOut(BaseModel):
    id: int
    code: str
    name: str
    kind: str
    icon: str | None = None
    icon_color: str | None = None
    operations: list[SectionOperationOut]


@router.get("/all/operations", response_model=list[SectionWithOperationsOut])
async def list_sections_with_operations(
    db: AsyncSession = Depends(get_db),
) -> list[SectionWithOperationsOut]:
    """List all active sections with their operations, filtered and resolved."""
    sections = (
        await db.execute(
            select(Section)
            .where(Section.is_active == True)
            .order_by(Section.sort_order, Section.id)
        )
    ).scalars().all()

    section_ids = [s.id for s in sections]
    ops_by_section = {}
    if section_ids:
        ops = (
            await db.execute(
                select(SectionOperation)
                .where(SectionOperation.section_id.in_(section_ids))
                .order_by(SectionOperation.sort_order, SectionOperation.id)
            )
        ).scalars().all()
        for op in ops:
            ops_by_section.setdefault(op.section_id, []).append(op)

    result = []
    for s in sections:
        section_ops = ops_by_section.get(s.id, [])
        # Исключаем служебные плейсхолдеры групп, например __xxx__
        filtered_ops = [
            op for op in section_ops
            if op.operation_code and not (op.operation_code.startswith("__") and op.operation_code.endswith("__"))
        ]

        # Если операций нет, делаем одну виртуальную
        if not filtered_ops:
            filtered_ops = [
                SectionOperation(
                    id=0,
                    section_id=s.id,
                    operation_code=s.code,
                    operation_name=s.name,
                    is_significant=True,
                )
            ]

        result.append(
            SectionWithOperationsOut(
                id=s.id,
                code=s.code,
                name=s.name,
                kind=s.kind,
                icon=s.icon,
                icon_color=s.icon_color,
                operations=[
                    SectionOperationOut(
                        id=op.id or 0,
                        operation_code=op.operation_code,
                        operation_name=op.operation_name,
                        is_significant=op.is_significant,
                        group_code=op.group_code,
                        group_name=op.group_name,
                    )
                    for op in filtered_ops
                ]
            )
        )
    return result
