from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, ConfigDict
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.models.import_template import ImportTemplate

router = APIRouter(prefix="/import-templates", tags=["import-templates"])


class ImportTemplateIn(BaseModel):
    name: str
    column_mapping: dict | None = None
    created_by: int | None = None


class ImportTemplateOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    name: str
    column_mapping: dict
    created_by: int | None
    created_at: datetime | None = None


@router.post("", response_model=ImportTemplateOut, status_code=status.HTTP_201_CREATED)
async def create_template(payload: ImportTemplateIn, db: AsyncSession = Depends(get_db)) -> ImportTemplateOut:
    data = payload.model_dump()
    if data.get("column_mapping") is None:
        data["column_mapping"] = {}
    item = ImportTemplate(**data)
    db.add(item)
    await db.flush()
    await db.refresh(item)
    return ImportTemplateOut.model_validate(item, from_attributes=True)


@router.get("", response_model=list[ImportTemplateOut])
async def list_templates(db: AsyncSession = Depends(get_db)) -> list[ImportTemplateOut]:
    items = (await db.execute(select(ImportTemplate).order_by(ImportTemplate.id))).scalars().all()
    return [ImportTemplateOut.model_validate(i, from_attributes=True) for i in items]


@router.get("/{template_id}", response_model=ImportTemplateOut)
async def get_template(template_id: int, db: AsyncSession = Depends(get_db)) -> ImportTemplateOut:
    item = await db.get(ImportTemplate, template_id)
    if item is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Import template not found")
    return ImportTemplateOut.model_validate(item, from_attributes=True)
