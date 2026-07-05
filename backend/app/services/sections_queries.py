from __future__ import annotations

from sqlalchemy import exists, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.models.section import Section
from app.models.spg import SpgSection, StorageProductionGroup

SECTION_SORT_FIELDS = frozenset({
    "id",
    "code",
    "name",
    "type",
    "sort_order",
    "description",
    "is_active",
})


def _apply_section_filters(
    stmt,
    *,
    search: str | None = None,
    type: str | None = None,
    is_active: bool | None = None,
    code: str | None = None,
    name: str | None = None,
    description: str | None = None,
    spg_id: int | None = None,
):
    if type:
        stmt = stmt.where(Section.type == type)
    if is_active is not None:
        stmt = stmt.where(Section.is_active.is_(is_active))
    if code:
        stmt = stmt.where(Section.code.ilike(f"%{code}%"))
    if name:
        stmt = stmt.where(Section.name.ilike(f"%{name}%"))
    if description:
        stmt = stmt.where(Section.description.ilike(f"%{description}%"))
    if spg_id is not None:
        stmt = stmt.where(
            exists(
                select(1)
                .select_from(SpgSection)
                .where(SpgSection.section_id == Section.id)
                .where(SpgSection.spg_id == spg_id)
            )
        )
    if search:
        search_like = f"%{search}%"
        stmt = stmt.where(
            or_(
                Section.code.ilike(search_like),
                Section.name.ilike(search_like),
                Section.description.ilike(search_like),
                exists(
                    select(1)
                    .select_from(
                        SpgSection.__table__.join(
                            StorageProductionGroup,
                            StorageProductionGroup.id == SpgSection.spg_id,
                        )
                    )
                    .where(SpgSection.section_id == Section.id)
                    .where(
                        or_(
                            StorageProductionGroup.code.ilike(search_like),
                            StorageProductionGroup.name.ilike(search_like),
                        )
                    )
                ),
            )
        )
    return stmt


def _resolve_section_order_column(sort_by: str):
    if sort_by == "code":
        return Section.code
    if sort_by == "name":
        return Section.name
    if sort_by == "type":
        return Section.type
    if sort_by == "description":
        return Section.description
    if sort_by == "is_active":
        return Section.is_active
    if sort_by == "id":
        return Section.id
    return Section.sort_order


async def list_sections_paginated(
    db: AsyncSession,
    *,
    limit: int,
    offset: int,
    search: str | None = None,
    sort_by: str = "sort_order",
    sort_order: str = "asc",
    type: str | None = None,
    is_active: bool | None = None,
    code: str | None = None,
    name: str | None = None,
    description: str | None = None,
    spg_id: int | None = None,
) -> tuple[list[Section], int]:
    resolved_sort_by = sort_by if sort_by in SECTION_SORT_FIELDS else "sort_order"
    order_column = _resolve_section_order_column(resolved_sort_by)

    stmt = select(Section).options(
        selectinload(Section.spg_links),
        selectinload(Section.operations),
    )
    stmt = _apply_section_filters(
        stmt,
        search=search,
        type=type,
        is_active=is_active,
        code=code,
        name=name,
        description=description,
        spg_id=spg_id,
    )

    count_stmt = select(func.count()).select_from(stmt.subquery())
    total = (await db.execute(count_stmt)).scalar() or 0

    if sort_order == "desc":
        stmt = stmt.order_by(order_column.desc().nulls_last(), Section.id.desc())
    else:
        stmt = stmt.order_by(order_column.asc().nulls_last(), Section.id.asc())

    stmt = stmt.limit(limit).offset(offset)
    sections = list((await db.execute(stmt)).scalars().unique().all())
    return sections, total