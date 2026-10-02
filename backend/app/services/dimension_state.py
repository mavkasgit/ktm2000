"""Миграция `product_dimensions` при смене размерности (Ref #72, ADR-0012).

Живёт в `services/`, а не в роутере, потому что переводить размерность умеют
две точки: карточка продукта (`products.py`) и импорт справочника из Excel
(#87). Правило одно — иначе импорт и карточка разъедутся при первой же
смене 1D → 2D.
"""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.models.dimension import DimensionType, ProductDimension
from app.models.product import DimensionState

# Поля размерности по состоянию: у линейного изделия размерности в габаритах
# нет, у плоского есть длина/ширина/толщина, у объёмного — длина/ширина/высота.
DIMENSION_FIELD_CODES: dict[DimensionState, set[str]] = {
    DimensionState.length: set(),
    DimensionState.area: {"length_mm", "width_mm", "thickness_mm"},
    DimensionState.volume: {"length_mm", "width_mm", "height_mm"},
}

# Все коды полей размерностей — граница для безопасного удаления при
# переключении (связи неразмерных типов, напр. weight, не трогаются).
ALL_DIMENSION_FIELD_CODES = set().union(*DIMENSION_FIELD_CODES.values())


async def migrate_dimensions_for_state(
    db: AsyncSession, product_id: int, state: DimensionState
) -> None:
    """Привести product_dimensions в соответствие с dimension_state (Ref #72).

    При переключении размерности поля 2D/3D ведутся через product_dimensions:
    - для целевой размерности создаются недостающие связи (пустые);
    - связи полей других размерностей удаляются (толщина ↔ высота);
    - существующие значения полей, входящих в целевую размерность, сохраняются;
    - связи неразмерных типов (напр. weight_mm) не трогаются.
    """
    target_codes = DIMENSION_FIELD_CODES[state]
    links = (
        await db.execute(
            select(ProductDimension)
            .options(selectinload(ProductDimension.dimension_type))
            .where(ProductDimension.product_id == product_id)
        )
    ).scalars().all()
    existing_by_code = {link.dimension_type.code: link for link in links}

    for code, link in existing_by_code.items():
        if code in ALL_DIMENSION_FIELD_CODES and code not in target_codes:
            await db.delete(link)

    missing = target_codes - set(existing_by_code)
    if missing:
        dim_types = (
            await db.execute(select(DimensionType).where(DimensionType.code.in_(missing)))
        ).scalars().all()
        type_by_code = {t.code: t for t in dim_types}
        for code in sorted(missing):
            dim_type = type_by_code.get(code)
            if dim_type is None:
                continue  # тип не в справочнике — пропускаем
            db.add(ProductDimension(product_id=product_id, dimension_type_id=dim_type.id))

    await db.flush()


async def set_dimension_defaults(
    db: AsyncSession,
    product_id: int,
    values: dict[str, float],
) -> int:
    """Проставить `default_value` у полей размерности артикула (#87).

    Поля, которых нет в связях артикула, молча пропускаются: набор связей
    задаёт `dimension_state`, и импорт не должен расширять его сам. Возвращает
    число проставленных значений — по нему видно, что файл доехал.
    """
    if not values:
        return 0
    links = (
        await db.execute(
            select(ProductDimension)
            .options(selectinload(ProductDimension.dimension_type))
            .where(ProductDimension.product_id == product_id)
        )
    ).scalars().all()
    by_code = {link.dimension_type.code: link for link in links}

    applied = 0
    for code, value in values.items():
        link = by_code.get(code)
        if link is None:
            continue
        if link.default_value is None or float(link.default_value) != float(value):
            link.default_value = float(value)
        applied += 1
    if applied:
        await db.flush()
    return applied