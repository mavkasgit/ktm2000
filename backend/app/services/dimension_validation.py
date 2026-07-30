"""Валидация dimensions продукта по привязкам справочника измерений (ADR-0001, п. 3).

Обязательное измерение без значения → подставляем default_value (типовой размер);
нет и его → доменная ошибка со списком недостающих измерений.
"""
from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.models.dimension import ProductDimension


class MissingDimensionsError(Exception):
    """Обязательные измерения без значения и без типового размера."""

    def __init__(self, missing_codes: list[str]):
        self.missing_codes = missing_codes
        super().__init__(f"Missing required dimensions: {', '.join(missing_codes)}")


async def resolve_product_dimensions(
    db: AsyncSession,
    product_id: int,
    dimensions: dict | None,
) -> dict | None:
    """Вернуть итоговый dict габаритов продукта с учётом привязок.

    - значение задано во входе → берём его;
    - не задано, но у привязки есть default_value → подставляем типовой размер;
    - is_required без значения и без default_value → MissingDimensionsError;
    - продукт без привязок → вход как есть (dict или None).
    """
    links = (
        await db.scalars(
            select(ProductDimension)
            .options(selectinload(ProductDimension.dimension_type))
            .where(ProductDimension.product_id == product_id)
        )
    ).all()

    if not links:
        return dimensions

    result: dict = dict(dimensions or {})
    missing: list[str] = []

    for link in links:
        code = link.dimension_type.code
        if result.get(code) is not None:
            continue
        if link.default_value is not None:
            result[code] = link.default_value
        elif link.is_required:
            missing.append(code)

    if missing:
        raise MissingDimensionsError(sorted(missing))

    return result if result else None
