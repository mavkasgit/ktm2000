from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.dimension import DimensionType, ProductDimension
from app.models.product import Product

# Базовые типы измерений. Новый тип размера = строка здесь, без миграции схемы.
DIMENSION_TYPES_DATA = [
    {"code": "length_mm", "name": "Длина", "unit": "мм", "value_type": "number"},
]


async def seed_dimension_types(db: AsyncSession) -> dict[str, int]:
    """Upsert dimension types + create length_mm bindings for products with length_mm.

    Product.length_mm хранится в миллиметрах (см. catalog_import / фронт «мм») —
    конвертация не нужна. Идемпотентно: тип обновляется по code, существующие
    привязки не перезаписываются (ручные правки сохраняются).
    """
    types_map: dict[str, DimensionType] = {}
    for data in DIMENSION_TYPES_DATA:
        dim_type = await db.scalar(select(DimensionType).where(DimensionType.code == data["code"]))
        if dim_type is None:
            dim_type = DimensionType(**data)
            db.add(dim_type)
            await db.flush()
        else:
            for key, value in data.items():
                setattr(dim_type, key, value)
        types_map[data["code"]] = dim_type

    length_type = types_map["length_mm"]

    existing_product_ids = set(
        (
            await db.scalars(
                select(ProductDimension.product_id).where(
                    ProductDimension.dimension_type_id == length_type.id
                )
            )
        ).all()
    )

    products = (
        await db.scalars(select(Product).where(Product.length_mm.is_not(None)))
    ).all()

    bindings_created = 0
    for product in products:
        if product.id in existing_product_ids:
            continue
        db.add(
            ProductDimension(
                product_id=product.id,
                dimension_type_id=length_type.id,
                is_required=True,
                default_value=product.length_mm,
            )
        )
        bindings_created += 1

    await db.flush()
    return {"dimension_types": len(types_map), "product_dimensions": bindings_created}
