from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.core.database import get_db
from app.models.dimension import DimensionType, ProductDimension
from app.models.product import Product
from app.schemas.dimensions import (
    DimensionTypeIn,
    DimensionTypeOut,
    DimensionTypePatch,
    ProductDimensionIn,
    ProductDimensionOut,
    ProductDimensionPatch,
)

router = APIRouter(tags=["dimensions"])


def _to_type_out(item: DimensionType) -> DimensionTypeOut:
    return DimensionTypeOut(
        id=item.id,
        code=item.code,
        name=item.name,
        unit=item.unit,
        value_type=item.value_type,
        created_at=item.created_at,
    )


def _to_link_out(link: ProductDimension) -> ProductDimensionOut:
    return ProductDimensionOut(
        id=link.id,
        product_id=link.product_id,
        dimension_type_id=link.dimension_type_id,
        is_required=link.is_required,
        default_value=link.default_value,
        dimension_type=_to_type_out(link.dimension_type),
    )


# --- Справочник dimension_types -------------------------------------------------


@router.get("/dimension-types", response_model=list[DimensionTypeOut])
async def list_dimension_types(db: AsyncSession = Depends(get_db)) -> list[DimensionTypeOut]:
    items = (await db.execute(select(DimensionType).order_by(DimensionType.code))).scalars().all()
    return [_to_type_out(i) for i in items]


@router.post("/dimension-types", response_model=DimensionTypeOut, status_code=status.HTTP_201_CREATED)
async def create_dimension_type(
    payload: DimensionTypeIn,
    db: AsyncSession = Depends(get_db),
) -> DimensionTypeOut:
    code = payload.code.strip()
    if not code:
        raise HTTPException(status_code=422, detail="code must not be empty")
    existing = await db.scalar(select(DimensionType).where(DimensionType.code == code))
    if existing:
        raise HTTPException(status_code=409, detail="Dimension type code already exists")
    item = DimensionType(code=code, name=payload.name, unit=payload.unit, value_type=payload.value_type)
    db.add(item)
    await db.flush()
    await db.refresh(item)
    return _to_type_out(item)


@router.patch("/dimension-types/{type_id}", response_model=DimensionTypeOut)
async def patch_dimension_type(
    type_id: int,
    payload: DimensionTypePatch,
    db: AsyncSession = Depends(get_db),
) -> DimensionTypeOut:
    item = await db.get(DimensionType, type_id)
    if item is None:
        raise HTTPException(status_code=404, detail="Dimension type not found")

    patch_data = payload.model_dump(exclude_unset=True)
    new_code = patch_data.pop("code", None)
    if new_code is not None:
        new_code = new_code.strip()
        if not new_code:
            raise HTTPException(status_code=422, detail="code must not be empty")
        if new_code != item.code:
            duplicate = await db.scalar(
                select(DimensionType).where(DimensionType.code == new_code, DimensionType.id != type_id)
            )
            if duplicate:
                raise HTTPException(status_code=409, detail="Dimension type code already exists")
            item.code = new_code

    for key, value in patch_data.items():
        setattr(item, key, value)

    await db.flush()
    return _to_type_out(item)


@router.delete("/dimension-types/{type_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_dimension_type(type_id: int, db: AsyncSession = Depends(get_db)):
    item = await db.get(DimensionType, type_id)
    if item is None:
        raise HTTPException(status_code=404, detail="Dimension type not found")

    links_count = await db.scalar(
        select(func.count()).select_from(ProductDimension).where(ProductDimension.dimension_type_id == type_id)
    )
    if links_count:
        raise HTTPException(status_code=409, detail="Нельзя удалить: измерение привязано к продуктам")

    await db.delete(item)
    await db.flush()


# --- Привязки измерений к продукту ----------------------------------------------


async def _get_product_or_404(db: AsyncSession, product_id: int) -> Product:
    product = await db.get(Product, product_id)
    if product is None:
        raise HTTPException(status_code=404, detail="Product not found")
    return product


@router.get("/products/{product_id}/dimensions", response_model=list[ProductDimensionOut])
async def list_product_dimensions(
    product_id: int,
    db: AsyncSession = Depends(get_db),
) -> list[ProductDimensionOut]:
    await _get_product_or_404(db, product_id)
    stmt = (
        select(ProductDimension)
        .options(selectinload(ProductDimension.dimension_type))
        .join(DimensionType, DimensionType.id == ProductDimension.dimension_type_id)
        .where(ProductDimension.product_id == product_id)
        .order_by(DimensionType.code)
    )
    links = (await db.execute(stmt)).scalars().all()
    return [_to_link_out(link) for link in links]


@router.post(
    "/products/{product_id}/dimensions",
    response_model=ProductDimensionOut,
    status_code=status.HTTP_201_CREATED,
)
async def create_product_dimension(
    product_id: int,
    payload: ProductDimensionIn,
    db: AsyncSession = Depends(get_db),
) -> ProductDimensionOut:
    await _get_product_or_404(db, product_id)

    dim_type = await db.get(DimensionType, payload.dimension_type_id)
    if dim_type is None:
        raise HTTPException(status_code=404, detail="Dimension type not found")

    existing = await db.scalar(
        select(ProductDimension).where(
            ProductDimension.product_id == product_id,
            ProductDimension.dimension_type_id == payload.dimension_type_id,
        )
    )
    if existing:
        raise HTTPException(status_code=409, detail="Dimension already linked to this product")

    link = ProductDimension(
        product_id=product_id,
        dimension_type_id=payload.dimension_type_id,
        is_required=payload.is_required,
        default_value=payload.default_value,
    )
    db.add(link)
    await db.flush()
    await db.refresh(link, attribute_names=["dimension_type"])
    return _to_link_out(link)


@router.patch("/products/{product_id}/dimensions/{link_id}", response_model=ProductDimensionOut)
async def patch_product_dimension(
    product_id: int,
    link_id: int,
    payload: ProductDimensionPatch,
    db: AsyncSession = Depends(get_db),
) -> ProductDimensionOut:
    link = await db.scalar(
        select(ProductDimension)
        .options(selectinload(ProductDimension.dimension_type))
        .where(ProductDimension.id == link_id, ProductDimension.product_id == product_id)
    )
    if link is None:
        raise HTTPException(status_code=404, detail="Product dimension not found")

    patch_data = payload.model_dump(exclude_unset=True)
    for key, value in patch_data.items():
        setattr(link, key, value)

    await db.flush()
    return _to_link_out(link)


@router.delete("/products/{product_id}/dimensions/{link_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_product_dimension(
    product_id: int,
    link_id: int,
    db: AsyncSession = Depends(get_db),
):
    link = await db.scalar(
        select(ProductDimension).where(
            ProductDimension.id == link_id, ProductDimension.product_id == product_id
        )
    )
    if link is None:
        raise HTTPException(status_code=404, detail="Product dimension not found")

    await db.delete(link)
    await db.flush()
