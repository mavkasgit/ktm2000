from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.dimension import DimensionType, ProductDimension
from app.models.product import Product
from app.seeds.dimension_types import DIMENSION_TYPES_DATA
from app.seeds.upsert import upsert_by_code

DIMENSION_TYPES_FIELD_MAP = {
    "code": "code",
    "name": "name",
    "unit": "unit",
    "value_type": "value_type",
}


async def seed_dimension_types(db: AsyncSession) -> dict[str, int]:
    """Upsert dimension types + create length_mm bindings for products with length_mm.

    Product.length_mm хранится в миллиметрах (см. catalog_import / фронт «мм») —
    конвертация не нужна. Идемпотентно: тип обновляется по code, существующие
    привязки не перезаписываются (ручные правки сохраняются).

    Основная часть (DimensionType) — через table-driven upsert; хвост
    (ProductDimension биндинги) — bespoke-блок вне хелпера (cross-entity).
    """
    types_map = await upsert_by_code(
        db,
        DimensionType,
        DIMENSION_TYPES_DATA,
        key_field="code",
        field_map=DIMENSION_TYPES_FIELD_MAP,
    )

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
        await db.scalars(select(Product).where(Product.attributes["length_mm"].is_not(None)))
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
