from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, Query, Response, status
from pydantic import BaseModel, ConfigDict
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.models.import_template import ImportTemplate

router = APIRouter(prefix="/import-templates", tags=["import-templates"])


class ImportTemplateIn(BaseModel):
    name: str
    code: str | None = None
    button_label: str | None = None
    is_active: bool = True
    sort_order: int = 0
    column_mapping: dict | None = None
    description: str | None = None
    created_by: int | None = None


class ImportTemplateOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    code: str | None = None
    name: str
    button_label: str | None = None
    is_active: bool
    sort_order: int
    column_mapping: dict
    description: str | None = None
    created_by: int | None = None
    created_at: datetime | None = None


class ImportTemplatesListResponse(BaseModel):
    items: list[ImportTemplateOut]
    total: int
    limit: int
    offset: int


@router.get("", response_model=ImportTemplatesListResponse)
async def list_templates(
    limit: int = Query(default=50, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
    db: AsyncSession = Depends(get_db),
) -> ImportTemplatesListResponse:
    base_stmt = select(ImportTemplate)
    total = (await db.execute(select(func.count()).select_from(base_stmt.subquery()))).scalar() or 0

    items = (
        await db.execute(
            base_stmt.order_by(ImportTemplate.sort_order.asc(), ImportTemplate.id.asc())
            .limit(limit)
            .offset(offset)
        )
    ).scalars().all()
    return ImportTemplatesListResponse(
        items=[await _template_out(db, item) for item in items],
        total=total,
        limit=limit,
        offset=offset,
    )


@router.post("", response_model=ImportTemplateOut, status_code=status.HTTP_201_CREATED)
async def create_template(payload: ImportTemplateIn, db: AsyncSession = Depends(get_db)) -> ImportTemplateOut:
    if not payload.name.strip():
        raise HTTPException(status_code=400, detail="Template name is required")

    clean_code = _clean_code(payload.code)
    if clean_code:
        existing = await db.scalar(select(ImportTemplate).where(ImportTemplate.code == clean_code))
        if existing is not None:
            raise HTTPException(status_code=409, detail="Template with this code already exists")

    data = payload.model_dump()
    data["code"] = clean_code
    data["name"] = payload.name.strip()
    if data.get("column_mapping") is None:
        data["column_mapping"] = {}
    item = ImportTemplate(**data)
    db.add(item)
    await db.flush()
    await db.refresh(item)
    return await _template_out(db, item)


@router.put("/{template_id}", response_model=ImportTemplateOut)
async def update_template(
    template_id: int,
    payload: ImportTemplateIn,
    db: AsyncSession = Depends(get_db),
) -> ImportTemplateOut:
    item = await db.get(ImportTemplate, template_id)
    if item is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Import template not found")

    if not payload.name.strip():
        raise HTTPException(status_code=400, detail="Template name is required")

    clean_code = _clean_code(payload.code)
    if clean_code:
        existing = await db.scalar(select(ImportTemplate).where(ImportTemplate.code == clean_code, ImportTemplate.id != template_id))
        if existing is not None:
            raise HTTPException(status_code=409, detail="Template with this code already exists")

    item.code = clean_code
    item.name = payload.name.strip()
    item.button_label = payload.button_label
    item.is_active = payload.is_active
    item.sort_order = payload.sort_order
    item.column_mapping = payload.column_mapping or {}
    item.description = payload.description
    await db.flush()
    await db.refresh(item)
    return await _template_out(db, item)


@router.delete("/{template_id}", status_code=status.HTTP_204_NO_CONTENT, response_class=Response, response_model=None)
async def delete_template(template_id: int, db: AsyncSession = Depends(get_db)) -> None:
    item = await db.get(ImportTemplate, template_id)
    if item is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Import template not found")
    await db.delete(item)
    await db.flush()


async def _template_out(db: AsyncSession, item: ImportTemplate) -> ImportTemplateOut:
    return ImportTemplateOut(
        id=item.id,
        code=item.code,
        name=item.name,
        button_label=item.button_label,
        is_active=item.is_active,
        sort_order=item.sort_order,
        column_mapping=item.column_mapping,
        description=item.description,
        created_by=item.created_by,
        created_at=item.created_at,
    )


def _clean_code(value: str | None) -> str | None:
    if value is None:
        return None
    stripped = value.strip()
    return stripped or None
