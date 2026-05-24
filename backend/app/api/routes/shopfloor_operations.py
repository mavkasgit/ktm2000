"""
GET  /api/shopfloor/sections/{section_id}/operations  — список операций участка
POST /api/shopfloor/sections/{section_id}/operations  — создать операцию
PATCH /api/shopfloor/sections/{section_id}/operations/{op_id} — обновить is_significant
DELETE /api/shopfloor/sections/{section_id}/operations/{op_id} — удалить операцию
"""
from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import READER_ROLES, require_role, get_db
from app.models.route import SectionOperation
from app.models.section import Section

router = APIRouter(prefix="/shopfloor/sections", tags=["shopfloor-operations"])


class CreateOperationSchema(BaseModel):
    operation_code: str
    operation_name: str
    is_significant: bool = False


@router.get("/{section_id}/operations")
async def get_section_operations(
    section_id: int,
    db: AsyncSession = Depends(get_db),
) -> list[dict]:
    """Список всех операций участка с is_significant."""
    # Проверим что участок существует
    section = await db.get(Section, section_id)
    if not section:
        return []

    rows = (
        await db.execute(
            select(SectionOperation)
            .where(SectionOperation.section_id == section_id)
            .order_by(SectionOperation.operation_code)
        )
    ).scalars().all()

    return [
        {
            "id": r.id,
            "operation_code": r.operation_code,
            "operation_name": r.operation_name,
            "is_significant": r.is_significant,
        }
        for r in rows
    ]


@router.post("/{section_id}/operations")
async def create_section_operation(
    section_id: int,
    payload: CreateOperationSchema,
    db: AsyncSession = Depends(get_db),
    _user=Depends(require_role(list(READER_ROLES))),
) -> dict:
    """Создать новую операцию для участка."""
    section = await db.get(Section, section_id)
    if not section:
        return {"error": "section not found"}

    # Проверим дубликат
    existing = (
        await db.execute(
            select(SectionOperation).where(
                SectionOperation.section_id == section_id,
                SectionOperation.operation_code == payload.operation_code,
            )
        )
    ).scalar_one_or_none()
    if existing:
        return {"error": "operation code already exists"}

    op = SectionOperation(
        section_id=section_id,
        operation_code=payload.operation_code,
        operation_name=payload.operation_name,
        is_significant=payload.is_significant,
    )
    db.add(op)
    await db.commit()
    await db.refresh(op)

    return {
        "id": op.id,
        "operation_code": op.operation_code,
        "operation_name": op.operation_name,
        "is_significant": op.is_significant,
    }


@router.delete("/{section_id}/operations/{op_id}")
async def delete_section_operation(
    section_id: int,
    op_id: int,
    db: AsyncSession = Depends(get_db),
    _user=Depends(require_role(list(READER_ROLES))),
) -> dict:
    """Удалить операцию участка."""
    op = await db.get(SectionOperation, op_id)
    if not op or op.section_id != section_id:
        return {"error": "not found"}

    await db.delete(op)
    await db.commit()
    return {"status": "ok"}


@router.patch("/{section_id}/operations/{op_id}")
async def update_section_operation(
    section_id: int,
    op_id: int,
    payload: dict,
    db: AsyncSession = Depends(get_db),
    _user=Depends(require_role(list(READER_ROLES))),
) -> dict:
    """Обновить is_significant для операции участка."""
    op = await db.get(SectionOperation, op_id)
    if not op or op.section_id != section_id:
        return {"error": "not found"}

    if "is_significant" in payload:
        op.is_significant = bool(payload["is_significant"])

    await db.commit()
    await db.refresh(op)

    return {
        "id": op.id,
        "operation_code": op.operation_code,
        "operation_name": op.operation_name,
        "is_significant": op.is_significant,
    }
