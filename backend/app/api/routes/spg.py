from decimal import Decimal
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, status, File, UploadFile, Form
from pydantic import BaseModel
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.api.deps import READER_ROLES, WRITER_ROLES, get_current_user, require_role
from app.core.database import get_db
from app.models.product import Product
from app.models.route import ProductionRoute, RouteStage, RouteRuleProfile, SectionOperation
from app.models.section import Section
from app.models.spg import SpgSection, StorageProductionGroup
from app.models.user import User
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
    type: str
    icon: str | None = None
    icon_color: str | None = None


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


# ─── Helpers ─────────────────────────────────────────────────────────────────


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
                type=sec.type,
                icon=sec.icon,
                icon_color=sec.icon_color,
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
    if not items:
        return []

    spg_ids = [item.id for item in items]
    bindings = (
        await db.execute(
            select(SpgSection)
            .where(SpgSection.spg_id.in_(spg_ids))
            .order_by(SpgSection.sort_order)
        )
    ).scalars().all()

    section_ids = {b.section_id for b in bindings}
    sec_map = {}
    if section_ids:
        sections = (
            await db.execute(select(Section).where(Section.id.in_(list(section_ids))))
        ).scalars().all()
        sec_map = {s.id: s for s in sections}

    bindings_by_spg: dict[int, list[SpgSection]] = {}
    for b in bindings:
        bindings_by_spg.setdefault(b.spg_id, []).append(b)

    result = []
    for item in items:
        spg_bindings = bindings_by_spg.get(item.id, [])
        sections_out = []
        for b in spg_bindings:
            sec = sec_map.get(b.section_id)
            if sec:
                sections_out.append(SpgSectionOut(
                    section_id=sec.id,
                    section_code=sec.code,
                    section_name=sec.name,
                    sort_order=b.sort_order,
                    type=sec.type,
                    icon=sec.icon,
                    icon_color=sec.icon_color,
                ))
        result.append(
            SpgOut(
                id=item.id,
                code=item.code,
                name=item.name,
                description=item.description,
                sort_order=item.sort_order,
                is_active=item.is_active,
                icon=item.icon,
                icon_color=item.icon_color,
                sections=sections_out,
            )
        )
    return result



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
