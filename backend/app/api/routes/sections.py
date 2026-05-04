from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.models.section import Section

router = APIRouter(prefix="/sections", tags=["sections"])


class SectionIn(BaseModel):
    code: str
    name: str
    description: str | None = None
    sort_order: int = 0
    is_active: bool = True
    kind: str = "production"
    icon: str | None = None
    icon_color: str | None = None


class SectionPatch(BaseModel):
    name: str | None = None
    description: str | None = None
    sort_order: int | None = None
    is_active: bool | None = None
    kind: str | None = None
    icon: str | None = None
    icon_color: str | None = None


class SectionOut(SectionIn):
    id: int


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
    item = Section(**payload.model_dump())
    db.add(item)
    await db.flush()
    await db.refresh(item)
    return SectionOut.model_validate(item, from_attributes=True)


@router.patch("/{section_id}", response_model=SectionOut)
async def patch_section(section_id: int, payload: SectionPatch, db: AsyncSession = Depends(get_db)) -> SectionOut:
    item = await db.get(Section, section_id)
    if item is None:
        raise HTTPException(status_code=404, detail="Section not found")
    for key, value in payload.model_dump(exclude_unset=True).items():
        setattr(item, key, value)
    await db.flush()
    await db.refresh(item)
    return SectionOut.model_validate(item, from_attributes=True)


@router.delete("/{section_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_section(section_id: int, db: AsyncSession = Depends(get_db)):
    item = await db.get(Section, section_id)
    if item is None:
        raise HTTPException(status_code=404, detail="Section not found")
    await db.delete(item)
    await db.flush()
