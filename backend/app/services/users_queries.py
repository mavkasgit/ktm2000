from __future__ import annotations

from sqlalchemy import String, cast, exists, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.section import Section
from app.models.user import User, user_sections

USER_SORT_FIELDS = frozenset({
    "id",
    "username",
    "full_name",
    "email",
    "role",
    "is_active",
    "created_at",
    "section",
})


def _user_section_codes_subquery():
    return (
        select(func.coalesce(func.string_agg(Section.code, ", "), ""))
        .select_from(user_sections.join(Section, Section.id == user_sections.c.section_id))
        .where(user_sections.c.user_id == User.id)
        .correlate(User)
        .scalar_subquery()
    )


def _apply_user_filters(
    stmt,
    *,
    search: str | None = None,
    role: str | None = None,
    is_active: bool | None = None,
    full_name: str | None = None,
    email: str | None = None,
    section: str | None = None,
):
    if role:
        stmt = stmt.where(User.role == role)
    if is_active is not None:
        stmt = stmt.where(User.is_active.is_(is_active))
    if full_name:
        stmt = stmt.where(User.full_name.ilike(f"%{full_name}%"))
    if email:
        stmt = stmt.where(User.email.ilike(f"%{email}%"))
    if section and section != "—":
        stmt = stmt.where(
            exists(
                select(1)
                .select_from(user_sections.join(Section, Section.id == user_sections.c.section_id))
                .where(user_sections.c.user_id == User.id)
                .where(Section.code.ilike(f"%{section}%"))
            )
        )
    if search:
        search_like = f"%{search}%"
        stmt = stmt.where(
            or_(
                User.full_name.ilike(search_like),
                User.username.ilike(search_like),
                User.email.ilike(search_like),
                cast(User.role, String).ilike(search_like),
            )
        )
    return stmt


def _resolve_user_order_column(sort_by: str):
    if sort_by == "username":
        return User.username
    if sort_by == "full_name":
        return User.full_name
    if sort_by == "email":
        return User.email
    if sort_by == "role":
        return User.role
    if sort_by == "is_active":
        return User.is_active
    if sort_by == "section":
        return _user_section_codes_subquery()
    if sort_by == "id":
        return User.id
    return User.created_at


async def list_users_paginated(
    db: AsyncSession,
    *,
    limit: int,
    offset: int,
    search: str | None = None,
    sort_by: str = "id",
    sort_order: str = "asc",
    role: str | None = None,
    is_active: bool | None = None,
    full_name: str | None = None,
    email: str | None = None,
    section: str | None = None,
) -> tuple[list[User], int]:
    resolved_sort_by = sort_by if sort_by in USER_SORT_FIELDS else "id"
    order_column = _resolve_user_order_column(resolved_sort_by)

    stmt = _apply_user_filters(
        select(User),
        search=search,
        role=role,
        is_active=is_active,
        full_name=full_name,
        email=email,
        section=section,
    )

    count_stmt = select(func.count()).select_from(stmt.subquery())
    total = (await db.execute(count_stmt)).scalar() or 0

    if sort_order == "desc":
        stmt = stmt.order_by(order_column.desc(), User.id.desc())
    else:
        stmt = stmt.order_by(order_column.asc(), User.id.asc())

    stmt = stmt.limit(limit).offset(offset)
    users = list((await db.execute(stmt)).scalars().all())
    return users, total


async def get_linked_hrms_ids(db: AsyncSession) -> list[int]:
    result = await db.execute(
        select(User.hrms_employee_id)
        .where(User.hrms_employee_id.is_not(None))
        .order_by(User.hrms_employee_id)
    )
    return [int(value) for value in result.scalars().all() if value is not None]