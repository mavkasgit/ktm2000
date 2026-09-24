from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.dimension import DimensionType, ProductDimension
from app.models.product import ProductLength
from app.seeds.dimension_types import DIMENSION_TYPES_DATA, DIMENSION_TYPES_FIELD_MAP
from app.seeds.upsert import upsert_by_key


async def seed_dimension_types(db: AsyncSession) -> dict[str, int]:
    """Upsert dimension types + create length_mm bindings for products with length_mm.
    Нормальные длины линейных артикулов берутся из ``product_lengths``.

    Значения длин приходят в миллиметрах; конвертация не нужна. Идемпотентно:
    тип обновляется по code, существующие привязки не перезаписываются
    (ручные правки сохраняются).

    Основная часть (DimensionType) — через table-driven upsert; хвост
    (ProductDimension биндинги) — bespoke-блок вне хелпера (cross-entity).
    """
    types_map = await upsert_by_key(
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

    length_rows = (
        await db.execute(
            select(ProductLength.product_id, ProductLength.length_mm, ProductLength.is_primary)
            .order_by(
                ProductLength.product_id,
                ProductLength.is_primary.desc(),
                ProductLength.length_mm,
            )
        )
    ).all()

    bindings_created = 0
    processed_product_ids: set[int] = set()
    for product_id, length_mm, _is_primary in length_rows:
        if product_id in existing_product_ids or product_id in processed_product_ids:
            continue
        processed_product_ids.add(product_id)
        db.add(
            ProductDimension(
                product_id=product_id,
                dimension_type_id=length_type.id,
                is_required=True,
                default_value=length_mm,
            )
        )
        bindings_created += 1

    await db.flush()
    return {"dimension_types": len(types_map), "product_dimensions": bindings_created}
