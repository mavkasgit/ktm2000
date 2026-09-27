from __future__ import annotations

from sqlalchemy import String, cast, exists, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.sorting import SortClause, apply_sort, parse_sort
from app.models.section import Section
from app.models.user import User, user_sections


def _user_section_codes_subquery():
    return (
        select(func.coalesce(func.string_agg(Section.code, ", "), ""))
        .select_from(user_sections.join(Section, Section.id == user_sections.c.section_id))
        .where(user_sections.c.user_id == User.id)
        .correlate(User)
        .scalar_subquery()
    )


# ─── Сортировка списка пользователей ────────────────────────────────────
# Единая таблица «поле ?sort= → выражение SQL»; она же — источник истины
# для валидации (apply_sort отвечает 400 на поле, которого здесь нет).
#
# Прямые колонки users лежат значением. ``section`` — коррелированный
# скалярный подзапрос (коды участков одной строкой через запятую), поэтому
# его выражение строится на каждый запрос и кладётся callable.
_SORT_COLUMNS: dict[str, object] = {
    "id": User.id,
    "username": User.username,
    "full_name": User.full_name,
    "email": User.email,
    "role": User.role,
    "is_active": User.is_active,
    "created_at": User.created_at,
    "section": lambda: _user_section_codes_subquery(),
}

# Курируемый набор полей сортировки: контракт для фронта. Выводится из
# таблицы резолва, а не живёт отдельно.
VALID_SORT_FIELDS = frozenset(_SORT_COLUMNS)

# Поля, где значение может быть пустым: необязательные колонки.
# Пустые уходят в конец в ЛЮБОМ направлении (в Postgres DESC по умолчанию
# ставит NULL первым — оператор кликнул «спустить», а незаполненные
# значения оказываются наверху).
_SORT_NULLS_LAST_FIELDS = ("email",)

# Порядок по умолчанию — тот же, что давал sort_by=id&sort_order=asc.
_SORT_DEFAULT = SortClause("id", "asc")




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



async def list_users_paginated(
    db: AsyncSession,
    *,
    limit: int,
    offset: int,
    search: str | None = None,
    sort: str | None = None,
    role: str | None = None,
    is_active: bool | None = None,
    full_name: str | None = None,
    email: str | None = None,
    section: str | None = None,
) -> tuple[list[User], int]:

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

    # Сортировка разбирается до выборки: неизвестное поле или направление —
    # 400, а не молчаливый фолбэк на id. Приоритеты слева направо, в конце
    # tiebreaker по PK (порядок строк между страницами не «мигает»).
    clauses = parse_sort(sort, default=_SORT_DEFAULT)
    stmt = apply_sort(
        stmt,
        clauses,
        _SORT_COLUMNS,
        tiebreaker=User.id,
        nulls_last=_SORT_NULLS_LAST_FIELDS,
    )

    stmt = stmt.limit(limit).offset(offset)
    users = list((await db.execute(stmt)).scalars().all())
    return users, total