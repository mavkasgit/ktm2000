from __future__ import annotations

from sqlalchemy import exists, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.core.sorting import SortClause, apply_sort, parse_sort
from app.models.section import Section
from app.models.spg import SpgSection, StorageProductionGroup

# ─── Сортировка справочника участков ────────────────────────────────────
# Единая таблица «поле ?sort= → выражение SQL». Она же — источник истины
# для валидации: apply_sort отвечает 400 на поле, которого здесь нет,
# поэтому поле нельзя объявить, но не зарезолвить (и наоборот).
_SORT_COLUMNS: dict[str, object] = {
    "id": Section.id,
    "code": Section.code,
    "name": Section.name,
    "type": Section.type,
    "sort_order": Section.sort_order,
    "description": Section.description,
    "is_active": Section.is_active,
}

# Курируемый набор полей сортировки: контракт для фронта. Выводится из
# таблицы резолва, а не живёт отдельно.
VALID_SORT_FIELDS = frozenset(_SORT_COLUMNS)

# Пустое значение уходит в конец в ЛЮБОМ направлении (в Postgres DESC по
# умолчанию ставит NULL первым). Список сохранён полным — как было до
# перехода на общий контракт: смена поведения сортировки без решения
# владельца недопустима. Практически nullable здесь только ``description``,
# остальные колонки NOT NULL, поэтому NULLS LAST на них — no-op.
_SORT_NULLS_LAST_FIELDS = (
    "id", "code", "name", "type", "sort_order", "description", "is_active",
)

# Порядок участков по умолчанию — тот же, что давал sort_by=sort_order&sort_order=asc.
_SORT_DEFAULT = SortClause("sort_order", "asc")



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


async def list_sections_paginated(
    db: AsyncSession,
    *,
    limit: int,
    offset: int,
    search: str | None = None,
    sort: str | None = None,
    type: str | None = None,
    is_active: bool | None = None,
    code: str | None = None,
    name: str | None = None,
    description: str | None = None,
    spg_id: int | None = None,
) -> tuple[list[Section], int]:

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

    # Сортировка разбирается до выборки: неизвестное поле или направление —
    # 400, а не молчаливый фолбэк на sort_order. Приоритеты слева направо,
    # в конце tiebreaker по PK (порядок строк между страницами не «мигает»).
    clauses = parse_sort(sort, default=_SORT_DEFAULT)
    stmt = apply_sort(
        stmt,
        clauses,
        _SORT_COLUMNS,
        tiebreaker=Section.id,
        nulls_last=_SORT_NULLS_LAST_FIELDS,
    )

    stmt = stmt.limit(limit).offset(offset)
    sections = list((await db.execute(stmt)).scalars().unique().all())
    return sections, total